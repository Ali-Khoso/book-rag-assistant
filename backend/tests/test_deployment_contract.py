"""Guard deployment boundaries: runtime secrets, worker isolation, and large uploads."""

import importlib.metadata
import json
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement
from pydantic import ValidationError

from tests.test_processing_pipeline import test_config

ROOT = Path(__file__).resolve().parents[2]


def test_docker_contexts_exclude_local_secrets_and_model_caches():
    backend = (ROOT/'backend/.dockerignore').read_text().splitlines()
    frontend = (ROOT/'frontend/.dockerignore').read_text().splitlines()
    assert '.env*' in backend and '.cache' in backend and '.venv' in backend
    assert '.env*' in frontend and 'node_modules' in frontend and '.next' in frontend
    assert 'deploy/*.env' in (ROOT/'.gitignore').read_text()
    assert '--require-hashes' in (ROOT/'backend/Dockerfile').read_text()


def test_compose_does_not_publish_api_model_or_worker_ports():
    services = yaml.safe_load((ROOT/'deploy/compose.yaml').read_text())['services']
    for name in ['api','web','worker','ollama']:
        assert not services[name].get('ports')
    assert services['api']['environment']['PROCESSING_ENABLED'] == 'false'
    assert services['worker']['command'] == ['python','-m','app.worker']
    assert services['worker']['healthcheck']['test'][-1] == '--check'
    assert services['api']['volumes'] and services['ollama']['volumes']


def test_frontend_build_has_only_public_configuration_and_no_upload_proxy():
    services = yaml.safe_load((ROOT/'deploy/compose.yaml').read_text())['services']
    assert set(services['web']['build']['args']) == {'NEXT_PUBLIC_SUPABASE_URL','NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY','NEXT_PUBLIC_API_URL'}
    vercel = json.loads((ROOT/'frontend/vercel.json').read_text())
    assert vercel['framework'] == 'nextjs' and not vercel.get('rewrites')


def test_installed_runtime_versions_satisfy_the_declared_requirements():
    for line in (ROOT/'backend/requirements.txt').read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'): continue
        requirement = Requirement(line)
        assert importlib.metadata.version(requirement.name) in requirement.specifier


def test_production_refuses_known_placeholder_monitor_tokens():
    with pytest.raises(ValidationError):
        test_config(environment='production', frontend_origin='https://books.vercel.app', limits_enabled=True,
            allowed_hosts=['api.example.com'], monitoring_token='REPLACE_WITH_A_RANDOM_32_CHARACTER_TOKEN')


def test_internal_model_http_requires_an_explicit_trusted_hostname():
    with pytest.raises(ValidationError): test_config(ollama_url='http://untrusted-model:11434')
    assert test_config(ollama_url='http://private-model:11434', ollama_allowed_http_hosts=['private-model']).ollama_url
