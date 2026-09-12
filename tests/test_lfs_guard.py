"""Compare real local Git clones; account credentials and network transports are excluded."""
import json
import os
from pathlib import Path
import random
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/lfs-guard.yml'
POINTER = 'version ' + 'https://git-lfs.github.com/spec/v1\noid sha256:' + 'a' * 64 + '\nsize 123\n'


class LfsGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='prawn-lfs-fixture-')
        self.base = Path(self.temporary.name).resolve()
        self.parent = self.base.parent
        self.addCleanup(self.cleanup)
        self.seed = self.base / 'source with spaces'
        self.seed.mkdir()
        self.hooks = self.base/'empty-hooks';self.hooks.mkdir()
        self.env = {k:v for k,v in os.environ.items() if k.upper() in
                    {'PATH','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','TEMP','TMP'}}
        self.env.update(GIT_CONFIG_GLOBAL=str(self.base/'gitconfig'), GIT_CONFIG_NOSYSTEM='1',
                        GIT_ALLOW_PROTOCOL='file', GIT_TERMINAL_PROMPT='0')
        self.git_exe = shutil.which('git')
        self.assertTrue(self.git_exe)
        self.git('init','--initial-branch=main',cwd=self.seed)
        self.git('config','user.name','Fixture',cwd=self.seed)
        self.git('config','user.email','fixture@example.invalid',cwd=self.seed)
        self.write('readme.txt','clean current content\n')
        self.commit('initial',['readme.txt'])
        self.clone_count = 0
        workflow = WORKFLOW.read_text(encoding='utf-8')
        scan = workflow.split('      - name: Scan for LFS pointer files\n',1)[1].split('        run: |\n',1)[1]
        self.script = '\n'.join(line[10:] if line.startswith('          ') else line for line in scan.splitlines())+'\n'
        command = re.search(r'POINTERS=\$\((git grep[^\n]+?)\)',self.script).group(1)
        command = command.removesuffix(' || true')
        self.scan_args = shlex.split(command)[1:]
        self.assertEqual(self.scan_args[0],'grep')

    def cleanup(self):
        self.assertEqual(self.base.resolve().parent,self.parent)
        self.assertTrue(self.base.name.startswith('prawn-lfs-fixture-'))
        def writable(function,path,_):
            candidate=Path(path).resolve()
            self.assertTrue(candidate.is_relative_to(self.base))
            os.chmod(path,stat.S_IWRITE)
            function(path)
        if self.base.exists():
            shutil.rmtree(self.base,onerror=writable)
        self.temporary.cleanup()

    def git(self,*args,cwd=None,check=True):
        return subprocess.run([self.git_exe,'-c','core.hooksPath='+str(self.hooks),
                               '-c','core.autocrlf=false','-c','pack.threads=1',*args],
                              cwd=cwd or self.base,env=self.env,check=check,
                              capture_output=True,text=True,encoding='utf-8',timeout=60)

    def write(self,name,content):
        path=self.seed/name
        self.assertTrue(path.resolve().is_relative_to(self.seed))
        path.parent.mkdir(parents=True,exist_ok=True)
        if isinstance(content,bytes):path.write_bytes(content)
        else:path.write_text(content,encoding='utf-8')

    def commit(self,message,paths):
        self.git('add','--',*paths,cwd=self.seed)
        self.git('commit','-m',message,cwd=self.seed)

    def clone(self,depth=None):
        self.clone_count+=1
        target=self.base/f'clone-{self.clone_count}'
        args=['clone','--no-local','--single-branch','--branch','main']
        if depth is not None:args+=['--depth',str(depth)]
        self.git(*args,self.seed.as_uri(),str(target))
        return target

    def compare(self,expected):
        clones=[self.clone(),self.clone(1)]
        for clone in clones:
            result=self.git(*self.scan_args,cwd=clone,check=False)
            self.assertIn(result.returncode,[0,1])
            self.assertEqual(set(result.stdout.splitlines()),set(expected))
        self.assertEqual(self.git('rev-parse','HEAD',cwd=clones[0]).stdout,
                         self.git('rev-parse','HEAD',cwd=clones[1]).stdout)
        self.assertEqual(self.git('rev-list','--count','HEAD',cwd=clones[1]).stdout.strip(),'1')
        return clones

    def test_workflow_uses_one_commit_for_its_current_index_scan(self):
        depths=re.findall(r'fetch-depth:\s*(\d+)',WORKFLOW.read_text())
        self.assertEqual(depths,['1'])

    def test_clean_current_commit_matches_in_both_clones(self):
        self.compare([])

    def test_current_nested_and_spaced_pointers_are_detected(self):
        names=['card.png','nested/with space.png','-leading.png']
        for name in names:self.write(name,POINTER)
        self.commit('pointer fixtures',names)
        self.compare(names)

    def test_removed_historical_pointer_does_not_block_current_content(self):
        self.write('old.png',POINTER);self.commit('historical pointer',['old.png'])
        self.git('rm','--cached','--','old.png',cwd=self.seed)
        self.git('commit','-m','remove old pointer from current tree',cwd=self.seed)
        self.compare([])

    def test_untracked_and_unstaged_content_does_not_change_index_scan(self):
        for clone in self.compare([]):
            (clone/'readme.txt').write_text(POINTER,encoding='utf-8')
            (clone/'untracked.png').write_text(POINTER,encoding='utf-8')
            self.assertEqual(self.git(*self.scan_args,cwd=clone,check=False).returncode,1)

    def test_merge_commit_pointer_is_detected_without_parent_history(self):
        self.git('switch','-c','feature',cwd=self.seed)
        self.write('feature.png',POINTER);self.commit('feature pointer',['feature.png'])
        self.git('switch','main',cwd=self.seed)
        self.write('main.txt','another line\n');self.commit('main change',['main.txt'])
        self.git('merge','--no-ff','feature','-m','merge fixture',cwd=self.seed)
        self.compare(['feature.png'])

    def test_shallow_clone_omits_removed_blob_history(self):
        self.write('historical.bin',random.Random(260912).randbytes(2*1024*1024))
        self.commit('historical payload',['historical.bin'])
        self.git('rm','--cached','--','historical.bin',cwd=self.seed)
        self.git('commit','-m','remove payload from current tree',cwd=self.seed)
        full,shallow=self.compare([])
        size=lambda root:sum(p.stat().st_size for p in (root/'.git/objects').rglob('*') if p.is_file())
        full_bytes,shallow_bytes=size(full),size(shallow)
        self.assertGreater(full_bytes,2*1024*1024)
        self.assertLess(shallow_bytes,full_bytes//100)
        print('LFS_FIXTURE_METRICS '+json.dumps({'full_object_bytes':full_bytes,'shallow_object_bytes':shallow_bytes,'current_index_equal':True}),flush=True)

    def run_script(self,directory):
        return subprocess.run(['bash','--noprofile','--norc','-c',self.script],cwd=directory,
                              env=self.env,capture_output=True,text=True,timeout=30)

    @unittest.skipIf(os.name=='nt','Exact Bash execution is verified on the hosted Linux runner')
    def test_exact_workflow_scan_accepts_clean_shallow_clone(self):
        self.assertEqual(self.run_script(self.clone(1)).returncode,0)

    @unittest.skipIf(os.name=='nt','Exact Bash execution is verified on the hosted Linux runner')
    def test_exact_workflow_scan_blocks_pointer_in_shallow_clone(self):
        self.write('current.png',POINTER);self.commit('pointer',['current.png'])
        result=self.run_script(self.clone(1))
        self.assertNotEqual(result.returncode,0)
        self.assertIn('current.png',result.stdout)

    @unittest.skipIf(os.name=='nt','Exact Bash execution is verified on the hosted Linux runner')
    def test_scan_errors_do_not_report_no_pointers(self):
        result=self.run_script(self.base)
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('No LFS pointer files found',result.stdout)


if __name__=='__main__':unittest.main()
