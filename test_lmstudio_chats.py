import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import lmstudio_chats
import providers
from server import Store


def step(identifier='1793208574594-0.25', incoming=20, outgoing=8):
    return dict(type='contentBlock', stepIdentifier=identifier, genInfo=dict(identifier='test-model',
                stats=dict(promptTokensCount=incoming, predictedTokensCount=outgoing),
                loadModelConfig=dict(fields=[dict(key='llm.load.contextLength', value=8192)])))


def chat():
    thinking=dict(type='contentBlock', style=dict(type='thinking'),
                  content=[dict(type='text', text='private reasoning', tokensCount=3)])
    return dict(name='Test chat', createdAt=1793208547072, assistantLastMessagedAt=1793208575000,
                systemPrompt='private system prompt',
                messages=[dict(versions=[dict(role='user', content='private user prompt')]),
                          dict(currentlySelected=1, versions=[dict(role='assistant', steps=[thinking, step()]),
                               dict(role='assistant', steps=[step('1793208575594-0.5', 40, 12)])])])


class ChatTests(unittest.TestCase):
    def test_exact_recorded_counts_versions_context_and_no_prompt_export(self):
        result=lmstudio_chats.parse_chat(Path('one.conversation.json'), chat(), 1793208580)
        self.assertEqual(result['totals'], dict(input=60,cached=0,write=0,output=20,reasoning=3,total=80))
        self.assertEqual(len(result['events']),2)
        self.assertEqual(result['events'][0]['at'],1793208574.594)
        self.assertEqual(result['context'],52)
        self.assertEqual(result['capacity'],8192)
        self.assertEqual(result['latest_usage']['input'],40)
        self.assertNotIn('private',json.dumps(result))
        self.assertEqual(result['usage_source'],'LM Studio chat file')

    def test_reused_steps_count_once_and_unreported_usage_stays_missing(self):
        data=chat()
        data['messages'].append(copy.deepcopy(data['messages'][1]))
        result=lmstudio_chats.parse_chat(Path('one.conversation.json'),data,1793208580)
        self.assertEqual(result['totals']['total'],80)
        data['messages']=[dict(versions=[dict(role='assistant',steps=[dict(genInfo=dict(stats=dict(totalTokensCount=100)))])])]
        result=lmstudio_chats.parse_chat(Path('one.conversation.json'),data,1793208580)
        self.assertEqual(result['usage_source'],'unavailable')
        self.assertEqual(result['events'],[])
        self.assertIsNone(result['context'])

    def test_unknown_step_ids_do_not_fabricate_times(self):
        data=chat();data['messages'][1]['versions'][0]['steps'][-1]['stepIdentifier']='unknown-id'
        result=lmstudio_chats.parse_chat(Path('one.conversation.json'),data,1793208580)
        self.assertIsNone(result['events'][0]['at'])
        self.assertEqual(result['totals']['total'],80)

    def test_cache_refresh_and_partial_writes_keep_last_good_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);path=folder/'one.conversation.json'
            path.write_text(json.dumps(chat()))
            reader=lmstudio_chats.Chats(folder)
            first=reader.read()[0]
            self.assertEqual(reader.files,1)
            with patch.object(lmstudio_chats,'parse_chat',side_effect=AssertionError('cache missed')):
                self.assertEqual(reader.read()[0],first)
            data=chat();data['messages'][1]['versions'].append(dict(role='assistant',steps=[step('1793208576594-0.8',3,2)]))
            path.write_text(json.dumps(data));self.assertEqual(reader.read()[0]['totals']['total'],85)
            path.write_text('{')
            self.assertEqual(reader.read()[0]['totals']['total'],85)
            self.assertTrue(reader.warnings)
            path.unlink();self.assertEqual(reader.read(),[])

    def test_store_provider_filter_and_native_only_json_autosave(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);folder=root/'conversations';folder.mkdir()
            path=folder/'one.conversation.json';path.write_text(json.dumps(chat()))
            settings=providers.Settings(None)
            settings.update(dict(enabled=dict(claude=False,codex=False,lmstudio=True)))
            store=Store(root/'codex',root/'claude',root/'history',settings=settings,lmstudio_folder=folder)
            store.archive.interval=0
            first=store.read()
            self.assertEqual([s['provider'] for s in first['sessions']],['lmstudio'])
            self.assertEqual(first['sessions'][0]['totals']['total'],80)
            self.assertEqual(first['sources'][0]['files'],1)
            data=chat();data['messages'][1]['versions'].append(dict(role='assistant',steps=[step('1793208576594-0.8',3,2)]))
            path.write_text(json.dumps(data));store.scanned=float('-inf')
            second=store.read()
            saved=store.archive.load(second['archive']['dates'][0])
            self.assertEqual(saved['sessions'][0]['totals']['total'],85)
            settings.update(dict(enabled=dict(lmstudio=False)));store.scanned=float('-inf')
            self.assertEqual(store.read()['sessions'],[])


if __name__=='__main__':
    unittest.main()
