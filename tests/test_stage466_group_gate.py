"""Stage 466: red guards for exact group evidence and aggregate freshness."""
import json
import time

import pytest

from scripts.real_group_gate import validate_manifest, validate_shard, validate_aggregate, load_latest_attempts


def fixture(tmp_path):
    node = 'tests/test_e2e_real.py::test_real_get_clients'
    manifest = {'schema_version': 1, 'marker_expression': 'real_api or real_browser',
                'groups': {'read': [node]}, 'required_nodes': [node], 'shared_helpers': []}
    shard = {'group': 'read', 'nodes': [node], 'manifest_hash': 'm',
             'created_at': time.time(),
             'runtime_fingerprint': 'r', 'test_fingerprint': 't',
             'contour_identity': 'c', 'dependency_fingerprint': 'd',
             'results': {'test': 0, 'cleanup': 0}, 'image_id': 'i'}
    (tmp_path / 'read.xml').write_text('<testsuite tests="1"><testcase classname="tests.test_e2e_real" name="test_real_get_clients"/></testsuite>')
    (tmp_path / 'read.outcome.json').write_text(json.dumps({'collected': 1, 'counts': {'passed': 1, 'failed': 0, 'skipped-not-configured': 0, 'skipped-error': 0}, 'nodes': {node: 'passed'}}))
    (tmp_path / 'summary.json').write_text(json.dumps({'results': {'cleanup': 0}}))
    (tmp_path / 'cleanup.log').write_text('')
    return manifest, shard


def test_manifest_exact_collect_and_duplicates(tmp_path):
    m, _ = fixture(tmp_path)
    validate_manifest(m, m['groups']['read'])
    with pytest.raises(ValueError): validate_manifest(m, [])
    m['groups']['read'].append(m['groups']['read'][0])
    with pytest.raises(ValueError): validate_manifest(m, m['groups']['read'])


@pytest.mark.parametrize('damage', ['xml', 'bad-xml', 'outcome', 'bad-outcome', 'skip', 'failure', 'duplicate-xml', 'missing-node', 'cleanup', 'cleanup-log', 'stale', 'runtime', 'test', 'manifest', 'contour', 'dependency'])
def test_shard_fail_closed(tmp_path, damage):
    m, s = fixture(tmp_path)
    if damage == 'xml': (tmp_path / 'read.xml').unlink()
    elif damage == 'bad-xml': (tmp_path / 'read.xml').write_text('<broken')
    elif damage == 'outcome': (tmp_path / 'read.outcome.json').unlink()
    elif damage == 'bad-outcome': (tmp_path / 'read.outcome.json').write_text('{broken')
    elif damage == 'duplicate-xml':
        case = '<testcase classname="tests.test_e2e_real" name="test_real_get_clients"/>'
        (tmp_path / 'read.xml').write_text(f'<testsuite tests="2">{case}{case}</testsuite>')
    elif damage == 'skip':
        (tmp_path / 'read.xml').write_text('<testsuite tests="1"><testcase classname="tests.test_e2e_real" name="test_real_get_clients"><skipped/></testcase></testsuite>')
    elif damage == 'failure':
        (tmp_path / 'read.xml').write_text('<testsuite tests="1"><testcase classname="tests.test_e2e_real" name="test_real_get_clients"><failure/></testcase></testsuite>')
    elif damage == 'missing-node': s['nodes'] = []
    elif damage == 'cleanup': s['results']['cleanup'] = 1
    elif damage == 'cleanup-log': (tmp_path / 'cleanup.log').unlink()
    elif damage == 'stale': s['created_at'] -= 86401
    else: s[{'runtime':'runtime_fingerprint','test':'test_fingerprint','manifest':'manifest_hash','contour':'contour_identity','dependency':'dependency_fingerprint'}[damage]] = 'wrong'
    with pytest.raises((ValueError, OSError)):
        validate_shard(m, s, tmp_path, {'manifest_hash':'m','runtime_fingerprint':'r','test_fingerprint':'t','contour_identity':'c','dependency_fingerprint':'d'})


def test_aggregate_requires_latest_every_group(tmp_path):
    m, s = fixture(tmp_path)
    expected = {'manifest_hash':'m','runtime_fingerprint':'r','test_fingerprint':'t','contour_identity':'c','dependency_fingerprint':'d'}
    validate_aggregate(m, {'read': [s]}, tmp_path, {'read':expected})
    with pytest.raises(ValueError): validate_aggregate(m, {}, tmp_path, {'read':expected})
    bad = dict(s, results={'test':1,'cleanup':0})
    with pytest.raises(ValueError): validate_aggregate(m, {'read':[s,bad]}, tmp_path, {'read':expected})


def test_image_id_comes_from_compose_service_image(monkeypatch):
    from scripts.run_isolated_test_suite import resolve_test_image_id
    calls = []
    def fake_output(command, **_kwargs):
        calls.append(command)
        if command[-3:] == ['config', '--format', 'json']:
            return json.dumps({'services': {'test': {'image': 'vetmanager-mcp-test'}}})
        if command == ['docker', 'image', 'inspect', 'vetmanager-mcp-test', '--format', '{{.Id}}']:
            return 'sha256:actual-image\n'
        raise AssertionError(command)
    monkeypatch.setattr('subprocess.check_output', fake_output)
    assert resolve_test_image_id(['docker', 'compose', '-p', 'isolated']) == 'sha256:actual-image'
    assert calls[-1][3] == 'vetmanager-mcp-test'


def _index(tmp_path, entries):
    (tmp_path / 'attempts.jsonl').write_text(''.join(
        json.dumps({'group': group, 'directory': directory}) + '\n'
        for group, directory in entries))


def _expected():
    return {'manifest_hash': 'm', 'runtime_fingerprint': 'r', 'test_fingerprint': 't',
            'contour_identity': 'c', 'dependency_fingerprint': 'd'}


def test_historical_incomplete_read_does_not_block_latest_green(tmp_path):
    latest = tmp_path / 'read-latest'
    latest.mkdir()
    manifest, shard = fixture(latest)
    (latest / 'shard.json').write_text(json.dumps(shard))
    _index(tmp_path, [('read', 'read-interrupted'), ('read', 'read-latest')])
    attempts = load_latest_attempts(tmp_path)
    assert len(attempts['read']) == 1
    assert validate_aggregate(manifest, attempts, tmp_path, {'read': _expected()})


@pytest.mark.parametrize('last_state', ['missing', 'invalid', 'red'])
def test_latest_missing_invalid_or_red_stays_fail_closed(tmp_path, last_state):
    old = tmp_path / 'read-old'
    old.mkdir()
    manifest, shard = fixture(old)
    (old / 'shard.json').write_text(json.dumps(shard))
    last = tmp_path / 'read-last'
    last.mkdir()
    if last_state == 'invalid':
        (last / 'shard.json').write_text('{invalid')
    elif last_state == 'red':
        fixture(last)
        (last / 'shard.json').write_text(json.dumps(dict(shard, results={'test': 1, 'cleanup': 0})))
    _index(tmp_path, [('read', 'read-old'), ('read', 'read-last')])
    with pytest.raises((ValueError, OSError)):
        attempts = load_latest_attempts(tmp_path)
        validate_aggregate(manifest, attempts, tmp_path, {'read': _expected()})


def test_latest_red_export_cannot_be_masked_by_green_read(tmp_path):
    read_dir = tmp_path / 'read-last'
    read_dir.mkdir()
    manifest, read = fixture(read_dir)
    (read_dir / 'shard.json').write_text(json.dumps(read))
    export_dir = tmp_path / 'export-last'
    export_dir.mkdir()
    fixture(export_dir)
    export_node = 'tests/test_stage276_live_export_download.py::test_real_export_is_downloaded_cleaned_and_served_by_us'
    manifest['groups']['export'] = [export_node]
    export = dict(read, group='export', nodes=[export_node], results={'test': 1, 'cleanup': 0})
    (export_dir / 'shard.json').write_text(json.dumps(export))
    _index(tmp_path, [('read', 'read-last'), ('export', 'export-last')])
    attempts = load_latest_attempts(tmp_path)
    assert set(attempts) == {'read', 'export'}
    with pytest.raises(ValueError, match='test or cleanup failed'):
        validate_aggregate(manifest, attempts, tmp_path, {'read': _expected(), 'export': _expected()})
