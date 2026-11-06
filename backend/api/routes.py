"""Dashboard endpoints backed by the application-owned services."""
from flask import Blueprint, abort, current_app, jsonify, request
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, ValidationError

from backend.models.providers import ProviderUpdate
from backend.services import claude_statusline, minimax, providers
from backend.parsers import local_proxy

blueprint = Blueprint('dashboard', __name__)


class ObjectPayload(BaseModel):
    model_config = ConfigDict(extra='allow')


class UpdatePreferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    notify: StrictBool | None = None
    dismiss: StrictStr | None = None


def payload(model=ObjectPayload):
    value = request.get_json()
    if not isinstance(value, dict):
        abort(400, 'Expected JSON object')
    try:
        return model.model_validate(value).model_dump(exclude_unset=True)
    except ValidationError as error:
        abort(400, str(error))


def services():
    return current_app.extensions


def apply_proxies(ext):
    store = ext['store']
    enabled = store.settings.enabled(store.detected)
    ext['proxies'].apply({tool: store.settings.ports(tool) for tool in local_proxy.TOOLS if tool in enabled})


def provider_status(ext):
    store = ext['store']
    store.detected = providers.detect(store.claude, store.codex, data_dir=store.limit_control.folder)
    proxies = ext['proxies'].status()
    local = {}
    for tool in local_proxy.TOOLS:
        listen, target = store.settings.ports(tool)
        local[tool] = dict(proxies[tool], listen=listen, target=target, server_up=local_proxy.reachable(target))
        if tool == 'lmstudio':
            local[tool]['chat_files'] = store.lmstudio.files
    return dict(settings=store.settings.snapshot(), enabled=sorted(store.settings.enabled(store.detected)),
                minimax=minimax.status(store.limit_control.folder or minimax.DEFAULT_DATA),
                detected=store.detected, names=providers.NAMES, cloud=list(providers.CLOUD), local=local)


@blueprint.get('/usage')
def usage():
    return jsonify(services()['store'].read())


@blueprint.get('/forecast')
def budget_forecast():
    return jsonify(services()['forecast'].payload(refresh=request.args.get('refresh') == '1'))


@blueprint.get('/quota')
def quota():
    """A compact quota view for the floating widget."""
    return jsonify(services()['store'].quota())


@blueprint.post('/refresh')
def refresh():
    payload()
    return jsonify(services()['store'].refresh_live())


@blueprint.get('/history/<day>')
def history(day):
    archive = services()['store'].archive
    if archive is None:
        abort(404)
    try:
        return jsonify(archive.load(day))
    except FileNotFoundError:
        abort(404, 'Day not found')
    except (OSError, ValueError) as error:
        abort(400, str(error))


@blueprint.get('/pricing')
def pricing():
    return jsonify(services()['pricing'].snapshot())


@blueprint.route('/limit-control', methods=['GET', 'POST'])
def limits():
    store = services()['store']
    if request.method == 'POST':
        try:
            store.limit_control.update(payload())
        except ValueError as error:
            abort(400, str(error))
        store.scanned = float('-inf')
    return jsonify(store.limit_control.snapshot())


@blueprint.route('/providers', methods=['GET', 'POST'])
def provider_settings():
    ext, store = services(), services()['store']
    if request.method == 'POST':
        value = payload(ProviderUpdate)
        try:
            if 'minimax' in value:
                minimax.validate(value['minimax'])
            store.settings.update(value)
            if 'minimax' in value:
                with store.live_lock:
                    minimax.configure(value['minimax'], store.limit_control.folder or minimax.DEFAULT_DATA)
                    store.live.pop('minimax', None)
                    store.live['checked_at'] = 0
                    if store.live_file:
                        claude_statusline.write_json(store.live_file, store.live)
        except ValueError as error:
            abort(400, str(error))
        except OSError:
            abort(500, 'Could not save provider settings')
        apply_proxies(ext)
        store.scanned = float('-inf')
    return jsonify(provider_status(ext))


@blueprint.get('/update')
def update_status():
    return jsonify(services()['updates'].status())


@blueprint.post('/update/settings')
def update_preferences():
    try:
        return jsonify(services()['updates'].set_preferences(payload(UpdatePreferences)))
    except ValueError as error:
        abort(400, str(error))


@blueprint.post('/update/install')
def install_update():
    payload()
    try:
        return jsonify(services()['updates'].start())
    except ValueError as error:
        abort(400, str(error))
