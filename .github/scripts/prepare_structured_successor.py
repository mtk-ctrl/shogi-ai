"""Prepare the next contextual model without resetting its learned parent.

This does not dispatch games or write Git refs. The caller must verify the
publication, build the new header, and pass parent-aware binary preflight
before freezing and launching the next explicitly bounded cycle.
"""
import argparse
import hashlib
import json
from pathlib import Path
from structured_execution import validate_execution

def prepare(package,old_execution,old_priors,cycle_id,seed_base,output,base,core):
    package=Path(package);result=json.loads((package/'result.json').read_text())
    if not(result.get('research_parent_updated') and result.get('next_selfplay_completed')):
        raise ValueError('a confirmed learned parent and its actual selfplay source are required')
    raw=(package/'next-model/model.json').read_bytes();model=json.loads(raw)
    if hashlib.sha256(raw).hexdigest()!=result.get('next_model_sha256'):
        raise ValueError('next model identity differs from the saved cycle result')
    if not model.get('eligible'):raise ValueError('next learned proposal is not eligible; retain the confirmed parent')
    parent=result['research_parent']
    if (model['parent_model_sha256']!=result['model_sha256']
            or model['parent_scale']!=result['selected_scale']
            or model['parent_options']!=core or parent['options']['StructuredEval'] is not True):
        raise ValueError('next model has lost its learned parent')
    execution=dict(schema='structured-cycle-execution-v1',cycle_id=cycle_id,max_games=1600,
        comparison_parent=dict(engine_ref=parent['engine_ref'],options=parent['options'],
                               model_sha256=parent['model_sha256']),
        training_publications=[result['next_publication']],
        seeds=dict(screens=[seed_base,seed_base+2000000,seed_base+4000000],
                   confirmation=seed_base+7000000,next_source=seed_base+12000000),
        used_seed_bases=sorted(set(old_execution['used_seed_bases']+old_execution['seeds']['screens']
            +[old_execution['seeds']['confirmation'],old_execution['seeds']['next_source']])))
    validate_execution(execution,model,base,core)
    priors=list(old_priors)+list(old_execution['training_publications'])
    priors.extend(r['publication'] for r in result['screens'])
    priors.append(result['confirmation_publication'])
    unique={}
    for receipt in priors:unique[(receipt['release'],receipt['name'])]=receipt
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    (output/'model.json').write_bytes(raw)
    sha=hashlib.sha256(raw).hexdigest()
    (output/'structured_value_weights.h').write_text('#pragma once\n#include <array>\nnamespace shogi::strategy {\n'
        'inline constexpr std::array<int,4893> StructuredValueWeights{'+','.join(map(str,model['weights']))+'};\n'
        'inline constexpr std::array<int,4893> StructuredParentWeights{'+','.join(map(str,model['parent_weights']))+'};\n'
        'inline constexpr const char* StructuredValueModel="'+sha+'";\n'
        'inline constexpr bool StructuredValueReady=true;\n}\n')
    for name,value in [('EXECUTION.json',execution),('parent-options.json',parent['options']),
                       ('prior-publications.json',list(unique.values()))]:
        (output/name).write_text(json.dumps(value,indent=2)+'\n')
    (output/'PLAN.md').write_text('# 学習評価を引き継いだ次世代の固定計画\n\n'
        '前世代で確認した学習済み評価表を親とし、新しい自己対局原本から学習した次の差分を検証する。'
        '学習済みの親を9配点だけの状態へ戻さない。条件の正本は同じcommitのEXECUTION.json。\n\n'
        f"- 循環ID: {cycle_id}\n- 親Engine: {parent['engine_ref']}\n- 親モデル: {parent['model_sha256']}\n"
        f"- 親の反映尺度: {model['parent_scale']}%\n- 新モデル: {sha}\n"
        '- 駒配置/玉距離/攻守/持駒/可動性を序中終で学ぶ4,893係数。固定した親評価表と新しい差分を保持する。\n'
        '- 3尺度の軽量検査後、各100局の選別、最良が50%以上なら別1000局の確認を1回だけ行う。\n'
        '- 全局と重複除外後の概算95%下限が双方50%超の場合だけ研究親を更新する。\n'
        '- 通過時は新親同士300局と、親評価表・使用済みデータを引き継いだ次の学習へ進む。最大1600新規局。\n'
        '- 双方200ms、長考/先読みON、2スレッド、同じ知識163件。空きrunnerを使用し他目的runを止めない。\n'
        '- 比較の前に親再現、全8走査モード、反転、基本駒取り、速度の実バイナリ検査を行う。\n'
        '- 全実戦手とモデル・実設定・保存・親子関係を検証する。正式main/既定値/版/知識を自動採用しない。\n'
        '- 不合格や材料不足は親保持で保存し、結果を見て確認を追加したり閾値を緩めたりしない。\n')
    return execution,model

if __name__=='__main__':
    import sys
    ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
    import selfplay_trial_transport as transport
    from tools.research.train_structured_value import PARENT
    p=argparse.ArgumentParser();p.add_argument('--package',required=True);p.add_argument('--execution',required=True)
    p.add_argument('--priors',required=True);p.add_argument('--cycle-id',required=True);p.add_argument('--seed-base',type=int,required=True)
    p.add_argument('--output',required=True);a=p.parse_args()
    prepare(a.package,json.loads(Path(a.execution).read_text()),json.loads(Path(a.priors).read_text()),
            a.cycle_id,a.seed_base,a.output,transport.BASE,PARENT)
