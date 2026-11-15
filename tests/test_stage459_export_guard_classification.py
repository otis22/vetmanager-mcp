"""Keep live export guard refusals distinct from other start errors."""

import pytest

from tests.test_stage385_export_outcome_live import _safe_export_start_refusal, _safe_export_poll_error


@pytest.mark.parametrize(('message', 'expected'), [
    ('CONSTRUCTOR_BUSY: wait before another attempt', 'CONSTRUCTOR_BUSY'),
    ('RUN_RATE_LIMITED: wait before another attempt', 'RUN_RATE_LIMITED'),
    ('Vetmanager tenant-wide REST export guard; wait 30 minutes', 'TENANT_GUARD'),
])
def test_known_guard_is_classified_without_raw_text(message, expected):
    result = {'result': {'isError': True, 'content': [{'type': 'text', 'text': message}]}}
    assert _safe_export_start_refusal(result) == expected


def test_other_start_error_is_not_called_guard():
    result = {'result': {'isError': True, 'content': [{'type': 'text',
              'text': 'REPORT_NOT_ALLOWED_FOR_REST with private detail'}]}}
    assert _safe_export_start_refusal(result) == 'OTHER_ERROR'


def test_missing_error_content_fails_closed():
    assert _safe_export_start_refusal({'result': {'isError': True}}) == 'OTHER_ERROR'


@pytest.mark.parametrize(('message', 'expected'), [
    ('FILE_BUILD_NOT_STARTED: wait for this file', 'FILE_BUILD_NOT_STARTED'),
    ('FILE_NOT_READY: wait for this file', 'FILE_NOT_READY'),
    ('Report export is not ready yet; retry same report_file_id', 'NOT_READY'),
])
def test_only_known_poll_not_ready_errors_are_retryable(message, expected):
    result = {'result': {'isError': True, 'content': [{'type': 'text', 'text': message}]}}
    assert _safe_export_poll_error(result) == expected


@pytest.mark.parametrize('message', [
    'NOT_FOUND: missing file',
    'authorization denied with private detail',
    'FILE_BUILD_FAILED: stop',
])
def test_other_poll_errors_are_not_called_build_delay(message):
    result = {'result': {'isError': True, 'content': [{'type': 'text', 'text': message}]}}
    assert _safe_export_poll_error(result) == 'OTHER_ERROR'
