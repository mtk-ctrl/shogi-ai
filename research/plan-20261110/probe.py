import os, subprocess, sys, re, json, time
ENG=os.environ.get("KUMOJI_ENGINE", "build/kumoji")
class E:
    def __init__(s, opts={}):
        s.p=subprocess.Popen([ENG],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
        s.send("usi"); s.wait("usiok")
        for k,v in opts.items(): s.send(f"setoption name {k} value {v}")
        s.send("isready"); s.wait("readyok"); s.send("usinewgame")
    def send(s,x): s.p.stdin.write(x+"\n"); s.p.stdin.flush()
    def wait(s,tok):
        lines=[]
        while True:
            l=s.p.stdout.readline()
            if not l: raise RuntimeError("eof")
            l=l.strip(); lines.append(l)
            if l.startswith(tok): return lines
    def go(s,moves,cmd):
        s.send("position startpos"+(" moves "+" ".join(moves) if moves else ""))
        t=time.time(); s.send(cmd); lines=s.wait("bestmove"); dt=time.time()-t
        return lines,dt
    def quit(s):
        s.send("quit"); s.p.wait()
def parse(lines):
    d={}
    for l in lines:
        if l.startswith("info nodes") and " string " in l:
            toks=l.split()
            d["nodes"]=int(toks[2])
            for i in range(4,len(toks)-1,2):
                try: d[toks[i]]=float(toks[i+1])
                except: pass
        m=re.match(r"info depth (\d+).*score (cp|mate) (-?\d+)",l)
        if m: d["depth"]=int(m.group(1)); d["score"]=int(m.group(3)) if m.group(2)=="cp" else 30000
    d["best"]=lines[-1].split()[1]
    return d
if __name__=="__main__":
    mode=sys.argv[1]
    if mode=="gen":
        games=[]
        for seed in (11,22,33):
            e=E({"AdaptiveLongThink":"false","USI_Ponder":"false","PositionKnowledge":"false"})
            moves=[]
            for ply in range(140):
                lines,_=e.go(moves,"go movetime 40")
                b=lines[-1].split()[1]
                if b in("resign","win"): break
                moves.append(b)
            e.quit(); games.append(moves); print(len(moves),file=sys.stderr)
        json.dump(games,open("games.json","w"))
