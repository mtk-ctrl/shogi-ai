"""Human-readable fixed SFEN pairs are valid positions and improve intended terms."""
import json
from pathlib import Path
import subprocess
import sys
cases=json.loads((Path(__file__).resolve().parents[1]/'benchmarks/positions/evaluation_cases.json').read_text())
sfens=[c[k] for c in cases for k in ('better','worse')]
rows=[json.loads(line) for line in subprocess.run([sys.argv[1]],input='\n'.join(sfens)+'\n',text=True,capture_output=True,check=True).stdout.splitlines()]
for i,c in enumerate(cases):
    better,worse=rows[2*i:2*i+2]
    assert better['material']==worse['material'],c['name']
    assert better[c['term']]>worse[c['term']],(c,better,worse)
    assert better['total']>worse['total'],(c,better,worse)
    print('PASS valid SFEN pair',c['name'],better[c['term']],'>',worse[c['term']],'; total',better['total'],'>',worse['total'])
