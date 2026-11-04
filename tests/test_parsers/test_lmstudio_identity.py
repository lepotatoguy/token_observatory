import os
from unittest.mock import patch

from backend.parsers.lmstudio import LmStudioChats


def test_inode_replacement_invalidates_same_size_and_timestamp(tmp_path):
    path = tmp_path / 'chat.conversation.json'
    path.write_text('{}')
    chats = LmStudioChats(tmp_path)
    with patch('backend.parsers.lmstudio.parse_chat', side_effect=[{'events': [], 'id': 'first'},
                                                                 {'events': [], 'id': 'second'}]) as parse:
        assert chats.read()[0]['id'] == 'first'
        stamp = path.stat().st_mtime_ns
        replacement = tmp_path / 'replacement.json'
        replacement.write_text('{}')
        os.utime(replacement, ns=(stamp, stamp))
        replacement.replace(path)
        assert chats.read()[0]['id'] == 'second'
        assert parse.call_count == 2
