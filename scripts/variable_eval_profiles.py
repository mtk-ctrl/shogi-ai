"""Research-only profiles. Generate auditable C++ anchors from this one source."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AXES = ['board_material','safety','pressure','activity','danger','influence',
        'potential','coordination','hand_potential','threat']
M = [100,480,380,410,150,140,210,340,60,20]
Q = [[200,450,390,560,135,245,300,900,56,30],
     [155,540,540,470,170,300,270,780,119,26],
     [110,740,670,380,225,180,180,570,250,22]]
H = [100,145,220]
PROFILES = []

def add(name, label, anchors=None, hand=None, curve='smooth', signal='maturity',
        context=False, reason='', family='axis', control=False, axis_signals=None,
        hand_signal=None):
    PROFILES.append(dict(index=len(PROFILES), name=name, label=label,
        anchors=[list(x) for x in (anchors if anchors is not None else Q)],
        hand_material=list(hand if hand is not None else H), curve=curve,
        signal=signal, context=context, reason=reason, family=family, control=control,
        axis_signals=axis_signals or {}, hand_signal=hand_signal))

def hybrid(changes):
    a=[list(M) for _ in range(3)]
    for axis, vals in changes.items():
        for i,v in enumerate(vals): a[i][AXES.index(axis)]=v
    return a

add('Q14', '現行Q14対照', context=True, control=True, family='control',
    reason='現行Q14を同じ研究コードで完全再現する対照')
add('M', '固定M対照', anchors=[M]*3, hand=[100]*3, control=True,
    family='control', reason='探索・駒単価・知識をそろえた固定M配点')
mean=[round((Q[0][i]+2*Q[1][i]+Q[2][i])/4) for i in range(10)]
add('FAVG', 'Q14平均配点を固定', anchors=[mean]*3, hand=[153]*3,
    family='control', reason='成熟度が均等分布する場合のQ14曲線の平均。可変性と平均配点を区別する')
add('NOC', '局面追加補正なし', context=False, family='context',
    reason='Q14の成熟度変化を残し危険度・戦闘度の追加補正だけ外す')
for name,label,curve,why in [
    ('LIN','直線補間','linear','三次補間の平坦区間が必要か'),
    ('DELAY','中盤から変化','delayed','成熟度35までは序盤配点、その後65点で全域を変化'),
    ('LATE','終盤寄り二乗曲線','late','成熟度をm²/100へ写し配点変化を遅らせる'),
    ('STEP','三段階の配点','step','33・66を境として配点を切り替える'),
    ('EARLY','序盤寄り平方根曲線','early','100√(m/100)で変化を早める')]:
    add(name,label,curve=curve,context=True,family='curve',reason=why)
for scale in [2,3]:
    a=[[max(0,M[i]+scale*(q[i]-M[i])) for i in range(10)] for q in Q]
    add('AMP'+str(scale),'Mからの変化幅'+str(scale)+'倍',anchors=a,
        hand=[100+scale*(h-100) for h in H], context=True,family='amplitude',
        reason='Q14とMの差を拡大。倍率を全項目へ一律に掛ける変更と区別する')
add('REV','配点の方向を逆転',anchors=list(reversed(Q)),hand=list(reversed(H)),
    family='direction',reason='序終盤の配点を反転。直感と反対の変化も検証する')
board={'board_material':[200,150,75]}
safety={'safety':[360,600,1440]}
hand={'hand_potential':[30,120,480]}
attack={'pressure':[190,570,1140], 'threat':[10,20,60]}
mobile={'activity':[820,410,205], 'coordination':[680,340,170]}
for name,label,changes,hm,why in [
    ('BOARD','M＋盤上駒得だけ可変',board,[100]*3,'盤上駒得の減少だけを切り分ける'),
    ('SAFE','M＋玉安全だけ可変',safety,[100]*3,'玉安全の序盤0.75倍・終盤3倍だけを試す'),
    ('HMAT','M＋持ち駒倍率だけ可変',{},[100,200,400],'持ち駒価値を最大4倍にする'),
    ('HPOT','M＋持ち駒潜在効果だけ可変',hand,[100]*3,'潜在効果をMの0.5・2・8倍にする'),
    ('ATTACK','M＋攻撃と脅威だけ可変',attack,[100]*3,'玉安全と攻撃の役割を分ける'),
    ('MOBILE','M＋活動と連携だけ可変',mobile,[100]*3,'活動・連携を序盤2倍から終盤0.5倍にする'),
    ('EXCHANGE','M＋盤上と持ち駒の融合',board,[100,200,400],'BOARDとHMATの相互作用'),
    ('KING','M＋玉安全と攻撃の融合',safety|attack,[100]*3,'SAFEとATTACKの相互作用'),
    ('HYBRID','M＋活動・玉安全・持ち駒',mobile|safety|hand,[100,200,400],
        'Mを土台に、活動から安全・持ち駒への重点移動を組み合わせる')]:
    add(name,label,anchors=hybrid(changes),hand=hm,family='interaction' if name in
        ('EXCHANGE','KING','HYBRID') else 'axis',reason=why)
add('BATTLE','戦闘度で攻撃へ移行',anchors=hybrid(safety|attack),hand=[100,150,200],
    signal='battle', family='gate',reason='成熟度を使わず戦闘度で配点を決める')
add('RISK','玉危険度で安全へ移行',anchors=hybrid(safety|{'danger':[150,300,600]}),
    hand=[100]*3,signal='risk',family='gate',reason='玉危険度だけで安全・駒危険を重くする')
add('BLEND','成熟度・戦闘度・玉危険度を合成',signal='blend',context=False,
    family='gate',reason='配点用指標=(5成熟度＋3戦闘度＋2危険度)/10。元の成熟度・詰み時間配分は変更しない')
add('RESOURCE','持ち駒量で手駒価値を変更',anchors=hybrid({'hand_potential':[60,120,360]}),
    hand=[100,200,400],signal='hand',family='gate',
    reason='両者の持ち駒量（歩1・香桂2・銀金3・角飛6、合計×4上限100）で手駒軸だけ変える')
add('UNIFIED','Q14＋盤上と持ち駒を同倍率',hand=[200,155,110],context=True,
    family='material_balance',reason='Q14の他軸を維持し持ち駒倍率を盤上と同じにする。駒打ちの点落ちを抑える')
add('POSITIONAL','M駒得＋Q14位置配点',anchors=[
    [100]+a[1:] for a in Q],hand=[100]*3,context=True,family='material_balance',
    reason='盤上・持ち駒をMに固定。Q14の位置配点変化だけを切り分ける')
add('RESOURCE_BALANCE','M＋同倍率駒得と手駒潜在効果',anchors=hybrid(
    board|{'hand_potential':[56,119,250]}),hand=[200,150,75],
    family='material_balance',reason='全駒共通の倍率を下げつつ、手駒の実用性を潜在効果で加点する')

# Freeze these ablations before any new comparison. The fixed mean is from
# 11,045 actually played ATTACK turns in the 200-game intermediate sample;
# its source hashes and rounding are recorded in attack-fixed-mean.json.
add('PRESS_ONLY','M＋攻撃圧力だけ可変',anchors=hybrid({'pressure':[190,570,1140]}),
    hand=[100]*3,family='ablation',
    reason='ATTACKから脅威の変化を除き、攻撃圧力の寄与を切り分ける')
add('THREAT_ONLY','M＋脅威だけ可変',anchors=hybrid({'threat':[10,20,60]}),
    hand=[100]*3,family='ablation',
    reason='ATTACKから攻撃圧力の変化を除き、脅威の寄与を切り分ける')
add('ATTACK_AVG','ATTACK実戦平均配点を固定',anchors=hybrid(
    {'pressure':[639]*3,'threat':[28]*3}),hand=[100]*3,family='ablation',
    reason='中間200局の自分の着手11,045件から平均を推定し固定。可変性と平均配点の増加を独立seedで比較する')

# Round 2: 40 new combinations, rather than further precision on old winners.
# Each family is a small factorial comparison so the next generation can use
# axis/curve contributions. These are selection hypotheses, not adopted values.
for curve in ['smooth','linear','delayed','late']:
    for gated in [False,True]:
        add(f'BAL_{curve}_{int(gated)}','攻撃＋玉安全＋駒危険',anchors=hybrid({
            'pressure':[450,750,1050],'safety':[480,720,1100],
            'danger':[150,240,360],'threat':[12,24,36]}),hand=[100]*3,
            curve=curve,family='round2_balance',
            axis_signals={'pressure':'battle','threat':'battle','safety':'risk','danger':'risk'} if gated else {},
            reason='同じ配点で曲線4種×成熟度一括/攻守別指標を比較する')
for direction,pressure in [('up',[480,800,1200]),('down',[1000,700,450])]:
    for tag,material in [('mild',[140,110,80]),('reverse',[80,110,140]),
                         ('wide',[180,100,60]),('flat',[100,100,100])]:
        add(f'MAT_{direction}_{tag}','攻撃＋盤上/持ち駒同倍率',anchors=hybrid({
            'pressure':pressure,'board_material':material}),hand=material,
            family='round2_material',reason='攻撃方向2種×駒得4種で相互作用を探索。脅威と他軸はM固定')
for curve in ['smooth','linear','late','early']:
    for reverse in [False,True]:
        changes={'pressure':[450,750,1050],
            'activity':[250,410,700] if reverse else [600,500,300],
            'coordination':[180,340,550] if reverse else [500,340,220],
            'influence':[180,240,120],'potential':[300,210,160]}
        add(f'MOB_{curve}_{int(reverse)}','攻撃＋活動/効き/連携',anchors=hybrid(changes),
            hand=[100]*3,curve=curve,family='round2_mobility',
            reason='活動/連携の増減方向2種×曲線4種。旧MOBILEをそのまま再測せず攻撃との融合を比較')
for curve in ['smooth','late']:
    for gated in [False,True]:
        for strong in [False,True]:
            add(f'HAND_{curve}_{int(gated)}_{int(strong)}','攻撃＋玉安全＋持ち駒実用性',
                anchors=hybrid({'pressure':[380,700,1100],'safety':[400,650,1000],
                    'hand_potential':[60,160,360] if strong else [30,90,180]}),
                hand=[100]*3,curve=curve,family='round2_hand',
                axis_signals={'pressure':'battle','safety':'risk','hand_potential':'hand'} if gated else {},
                reason='材料倍率を固定し、持ち駒潜在2強度×判定2種×曲線2種。持ち駒倍率の過大化を避ける')
for tag,pressure in [('middle_peak',[600,1200,600]),('middle_dip',[1000,500,1000]),
                      ('end_surge',[800,800,1600]),('reverse',[1200,800,400])]:
    for curve in ['smooth','step']:
        add(f'SHAPE_{tag}_{curve}','非単調/急変攻撃＋危険連動の守り',
            anchors=hybrid({'pressure':pressure,'safety':[450,800,1100],'danger':[150,200,330]}),
            hand=[100]*3,curve=curve,axis_signals={'safety':'risk','danger':'risk'},
            family='round2_shape',reason='中盤ピーク/谷/終盤急増/逆方向の4形×滑らか/段階。玉安全は独立した危険度で判断')

CURVES=['smooth','linear','delayed','late','step','early']
SIGNALS=['maturity','battle','risk','blend','hand']

def header():
    rows=[]
    for p in PROFILES:
        signals=','.join(str(SIGNALS.index(p['axis_signals'][a])) if a in p['axis_signals'] else '-1' for a in AXES)
        hand_signal=-1 if p['hand_signal'] is None else SIGNALS.index(p['hand_signal'])
        stages=','.join('std::array<int,10>{{'+','.join(map(str,a))+'}}' for a in p['anchors'])
        rows.append('    ResearchPhaseProfile{std::array<std::array<int,10>,3>{{'+stages+'}}, std::array<int,3>{{'+
            ','.join(map(str,p['hand_material']))+'}}, '+
            str(CURVES.index(p['curve']))+', '+str(SIGNALS.index(p['signal']))+
            ', '+str(p['context']).lower()+', std::array<int,10>{{'+signals+'}}, '+str(hand_signal)+'}, // '+p['name'])
    return '''#pragma once
// Generated from scripts/variable_eval_profiles.py; candidate research only.
#include <array>
namespace shogi::strategy {
struct ResearchPhaseProfile {
    std::array<std::array<int,10>,3> anchors;
    std::array<int,3> hand_material;
    int curve, signal;
    bool context;
    std::array<int,10> axis_signals;
    int hand_signal;
};
inline constexpr std::array<ResearchPhaseProfile,'''+str(len(PROFILES))+'''> ResearchProfiles{{
'''+ '\n'.join(rows)+'''
}};
} // namespace shogi::strategy
'''

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--generate',action='store_true')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    hp=ROOT/'engine/research/variable_profiles.h'
    jp=ROOT/'research/variable-eval-20261012/profiles.json'
    meta=json.dumps(dict(axes=AXES,reference_m=M,profiles=PROFILES),ensure_ascii=False,indent=2)+'\n'
    if args.generate:
        hp.parent.mkdir(parents=True,exist_ok=True);jp.parent.mkdir(parents=True,exist_ok=True)
        hp.write_text(header());jp.write_text(meta)
    if args.check:
        assert hp.read_text()==header(),'generated header mismatch'
        assert jp.read_text()==meta,'generated profile registry mismatch'
    print(f'{len(PROFILES)} profiles; exact Q14 and fixed M controls, {len(PROFILES)-2} research variants')

if __name__=='__main__': main()
