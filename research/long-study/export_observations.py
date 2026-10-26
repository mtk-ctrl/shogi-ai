#!/usr/bin/env python3
"""Export archived research, preserving provenance. Does not import training labels."""
import argparse
import contextlib
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=Path(__file__).with_name('catalog-20261026.json'))
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text())
    args.cache.mkdir(parents=True, exist_ok=True)
    for asset in catalog['assets']:
        assert Path(asset['name']).name == asset['name'], 'unsafe asset name'
        path = args.cache / asset['name']
        if not path.exists() and args.download:
            temporary = path.with_name(path.name + '.download')
            with urllib.request.urlopen(asset['url'], timeout=120) as response, temporary.open('wb') as target:
                shutil.copyfileobj(response, target)
            assert temporary.stat().st_size == asset['bytes'] and digest(temporary) == asset['sha256']
            temporary.replace(path)
        assert path.is_file() and path.stat().st_size == asset['bytes'] and digest(path) == asset['sha256'], asset['name']
    assert not args.output.exists(), 'Choose a new output path; preserve prior exports.'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = args.output.with_name(args.output.name + '.partial')
    count = 0
    seen = set()
    with temporary_output.open('w') as output:
        for source in catalog['sources']:
            fmt = source['format']
            if fmt == 'neural20-checkpoint-v1':
                path = args.cache / (source['manifest_asset'] + '.tgz')
                if not path.exists():
                    temporary = path.with_name(path.name + '.partial')
                    with temporary.open('wb') as target:
                        for part in source['parts']:
                            with (args.cache / part['name']).open('rb') as stream:
                                shutil.copyfileobj(stream, target)
                    assert digest(temporary) == source['bundle_sha256']
                    temporary.replace(path)
                assert digest(path) == source['bundle_sha256']
                manager = tarfile.open(path)
            elif fmt == 'tar-gzip':
                manager = tarfile.open(args.cache / source['asset'])
            else:
                manager = contextlib.nullcontext(None)
            with manager as archive:
                for group in catalog['groups']:
                    if group['source_id'] != source['id']:
                        continue
                    if archive is not None:
                        data = archive.extractfile(group['member']).read()
                        assert hashlib.sha256(data).hexdigest() == group['member_sha256']
                    else:
                        data = gzip.decompress((args.cache / source['asset']).read_bytes())
                        assert hashlib.sha256(data).hexdigest() == source['decoded_sha256']
                    rows = [json.loads(x) for x in data.splitlines() if x] if fmt == 'gzip-jsonl' else json.loads(data)
                    for key in group['pointer'].split('/')[1:]:
                        rows = rows[int(key)] if isinstance(rows, list) else rows[key]
                    assert isinstance(rows, list) and len(rows) == group['observations']
                    for index, row in enumerate(rows):
                        observation_id = group['id'] + ':' + str(index)
                        assert observation_id not in seen
                        seen.add(observation_id)
                        item = dict(observation_id=observation_id, group_id=group['id'], record_index=index, record=row)
                        output.write(json.dumps(item, ensure_ascii=False, separators=(',', ':')) + '\n')
                        count += 1
    assert count == catalog['summary']['observations']
    temporary_output.replace(args.output)
    print(json.dumps(dict(observations=count, output_sha256=digest(args.output))))


if __name__ == '__main__':
    main()
