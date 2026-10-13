import json

from robot_agent.online_agent import OnlineAgent, SimulatedDevices


class FixedProvider:
    def __init__(self, *outputs):
        self.outputs = iter(outputs)

    def complete(self, text):
        return next(self.outputs)


def output(functions=(), response='你好，我是小沫。'):
    return json.dumps({'function': list(functions), 'response': response}, ensure_ascii=False)


def test_text_dialogue_returns_reply_without_actions():
    result = OnlineAgent(FixedProvider(output()), SimulatedDevices()).submit('你好')
    assert result == {'success': True, 'response': '你好，我是小沫。', 'actions': []}


def test_parameter_alias_duplicate_and_next_turn():
    agent = OnlineAgent(FixedProvider(output(['volume_set(30)', 'volume_set(30)', 'head_left']),
                                      output(['volume_status']), output(['head_left'])), SimulatedDevices())
    first = agent.submit('音量三十，向左看')
    assert len(first['actions']) == 2
    assert all(a['success'] and a['simulated'] for a in first['actions'])
    assert agent.submit('音量多少')['actions'][0]['result']['volume'] == 30
    assert agent.submit('再向左看')['actions'][0]['success']
    alias = OnlineAgent(FixedProvider(output(['play_song("小幸运")'])), SimulatedDevices()).submit('播放')
    assert alias['actions'][0]['result']['song'] == '小幸运'


def test_different_actions_can_execute_concurrently():
    import threading

    class ConcurrentDevices:
        def __init__(self):
            self.ready = threading.Barrier(2)

        def execute(self, name, args):
            self.ready.wait(timeout=2)
            return {'success': True, 'simulated': True, 'result': name}

    result = OnlineAgent(FixedProvider(output(['head_left', 'volume_mute'])), ConcurrentDevices()).submit('做两个动作')
    assert result['success']
    assert {a['result'] for a in result['actions']} == {'head_left', 'volume_mute'}


def test_invalid_unknown_and_unimplemented_actions_never_report_success():
    for call in ['unknown', 'start_following', 'volume_set(nan)', 'head_left(1)', 'volume_set(__import__("os"))']:
        result = OnlineAgent(FixedProvider(output([call], '已完成。')), SimulatedDevices()).submit('执行')
        assert result['success'] is False
        assert result['actions'][0]['success'] is False
        assert '动作失败' in result['response']


def test_invalid_protocol_and_network_failure_have_observable_feedback():
    for raw in ['bad json', '{"fc":[],"res":"你好"}', '{"function":[],"response":1}',
                '{"function":[],"function":["head_left"],"response":"你好"}']:
        result = OnlineAgent(FixedProvider(raw), SimulatedDevices()).submit('你好')
        assert result['error'] == 'invalid_output'
        assert result['actions'] == []
    result = OnlineAgent(FixedProvider(), SimulatedDevices()).submit('你好')
    assert result['error'] == 'provider_failed'
    assert result['response']


def test_simulated_music_state_is_observable_in_later_turns():
    agent = OnlineAgent(FixedProvider(output(['play_music(小幸运)']), output(['music_status']),
                                     output(['stop_music']), output(['music_status'])), SimulatedDevices())
    assert agent.submit('播放')['actions'][0]['result']['song'] == '小幸运'
    assert agent.submit('查询')['actions'][0]['result']['is_playing'] is True
    assert agent.submit('停止')['actions'][0]['success']
    assert agent.submit('查询')['actions'][0]['result']['is_playing'] is False
