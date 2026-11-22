import unittest
from unittest.mock import MagicMock
from youtube_guvenlik import yayin_guvenlik_kontrolu


class YouTubeSafetyTest(unittest.TestCase):
    def client(self, pages=None, videos=None):
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {'items': [{'id': 'channel'}]}
        youtube.search().list().execute.side_effect = pages or [{'items': []}]
        youtube.videos().list().execute.return_value = {'items': videos or []}
        return youtube

    def item(self, title='Diğer video', publish_at=None):
        status = {'privacyStatus': 'private'}
        if publish_at:
            status['publishAt'] = publish_at
        return {'id':'v1', 'snippet':{'channelId':'channel', 'title':title}, 'status':status}

    def page(self):
        return [{'items':[{'id': {'videoId':'v1'}}]}]

    def test_empty_channel_is_safe(self):
        yayin_guvenlik_kontrolu(self.client(), 'Yeni başlık', '2026-11-22T16:30Z')

    def test_existing_title_blocks(self):
        with self.assertRaisesRegex(RuntimeError, 'başlık'):
            yayin_guvenlik_kontrolu(self.client(self.page(), [self.item(title='YENİ BAŞLIK')]), 'Yeni başlık', '2026-11-22T16:30Z')

    def test_same_day_scheduled_video_blocks(self):
        with self.assertRaisesRegex(RuntimeError, 'planlı'):
            yayin_guvenlik_kontrolu(self.client(self.page(), [self.item(publish_at='2026-11-22T17:30:00Z')]), 'Yeni başlık', '2026-11-22T16:30Z')

    def test_next_day_scheduled_video_does_not_block(self):
        yayin_guvenlik_kontrolu(self.client(self.page(), [self.item(publish_at='2026-11-23T16:30:00Z')]), 'Yeni başlık', '2026-11-22T16:30Z')

    def test_incomplete_pagination_blocks(self):
        with self.assertRaisesRegex(RuntimeError, 'tamamlanamadı'):
            yayin_guvenlik_kontrolu(self.client([{'items':[], 'nextPageToken':'next'}]), 'Yeni başlık', max_pages=1)

    def test_incomplete_details_blocks(self):
        with self.assertRaisesRegex(RuntimeError, 'eksik'):
            yayin_guvenlik_kontrolu(self.client(self.page(), []), 'Yeni başlık')

    def test_wrong_channel_blocks(self):
        item=self.item(); item['snippet']['channelId']='other'
        with self.assertRaisesRegex(RuntimeError, 'kanal'):
            yayin_guvenlik_kontrolu(self.client(self.page(), [item]), 'Yeni başlık')

    def test_bad_schedule_time_blocks(self):
        with self.assertRaisesRegex(RuntimeError, 'saati'):
            yayin_guvenlik_kontrolu(self.client(self.page(), [self.item(publish_at='invalid')]), 'Yeni başlık', '2026-11-22T16:30Z')


if __name__ == '__main__':
    unittest.main()
