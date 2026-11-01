import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import sheets_metadata as m


def meta(name, *, ready=True, link='', row=1, col='beden_beyin'):
    return {
        'row': row, 'status': 'BEKLEMEDE' if ready else 'ASKIDA',
        'title': f'Title for {name}', 'description': 'description', 'tags': ['bilim'],
        'categoryId': '27', 'category_name': 'insan', 'column_group': col,
        'pinned_comment': '', 'has_youtube_link': bool(link), 'youtube_url': link,
        'is_ready': ready,
    }


def item(name, file_id=None):
    return {'id': file_id or f'id-{name}', 'name': name, 'size': '1024'}


class SequentialQueueTests(unittest.TestCase):
    def select(self, table, videos, skip=(), kind='short', force=None):
        with patch.object(m, 'load_table_from_drive_or_local', return_value=table), \
             patch.object(m, 'list_drive_videos', return_value=videos):
            return m.get_next_scheduled_video(object(), 'queue', skip_ids=set(skip),
                                              video_type=kind, force_file=force)

    def test_starts_at_155_even_if_out_of_order_and_other_category(self):
        table={n: meta(n, row=100-i, col='doz_disi') for i,n in enumerate(['video_155.mp4','video_156.mp4','video_158.mp4'])}
        result=self.select(table,[item('video_158.mp4'),item('video_156.mp4'),item('video_155.mp4')],force='video_148.mp4')
        self.assertEqual(result['name'],'video_155.mp4')

    def test_published_155_advances_to_156(self):
        table={n: meta(n) for n in ['video_155.mp4','video_156.mp4','video_158.mp4']}
        result=self.select(table,[item(n) for n in table],skip=['video_155.mp4'])
        self.assertEqual(result['name'],'video_156.mp4')

    def test_youtube_link_alone_counts_as_publication(self):
        table={'video_155.mp4':meta('video_155.mp4',ready=False,link='https://youtu.be/x'),
               'video_156.mp4':meta('video_156.mp4')}
        self.assertEqual(self.select(table,[item('video_156.mp4')])['name'],'video_156.mp4')

    def test_missing_next_does_not_jump_ahead(self):
        table={n: meta(n) for n in ['video_155.mp4','video_156.mp4','video_158.mp4']}
        self.assertIsNone(self.select(table,[item('video_158.mp4')],skip=['video_155.mp4']))

    def test_held_next_does_not_count_as_published_or_get_bypassed(self):
        table={'video_155.mp4':meta('video_155.mp4',ready=False),'video_156.mp4':meta('video_156.mp4')}
        self.assertIsNone(self.select(table,[item('video_155.mp4'),item('video_156.mp4')]))

    def test_known_published_157_skipped_after_156(self):
        done=['video_155.mp4','video_156.mp4']
        table={'video_157.mp4':meta('video_157.mp4'), 'video_158.mp4':meta('video_158.mp4')}
        result=self.select(table,[item(n) for n in table],skip=done)
        self.assertEqual(result['name'],'video_158.mp4')

    def test_matching_duplicate_names_refuse_publication(self):
        table={'video_155.mp4':meta('video_155.mp4')}
        self.assertIsNone(self.select(table,[item('video_155.mp4','a'),item('video_155.mp4','b')]))

    def test_long_starts_at_8_and_skips_published_17(self):
        names=['uzun_video_9.mp4','uzun_video_8.mp4','uzun_video_10.mp4']
        table={n:meta(n,row=i) for i,n in enumerate(names)}
        self.assertEqual(self.select(table,[item(n) for n in names],kind='long')['name'],'uzun_video_8.mp4')
        done=[f'uzun_video_{n}.mp4' for n in range(8,17)]
        table2={'uzun_video_17.mp4':meta('uzun_video_17.mp4'),'uzun_video_18.mp4':meta('uzun_video_18.mp4')}
        self.assertEqual(self.select(table2,[item(n) for n in table2],skip=done,kind='long')['name'],'uzun_video_18.mp4')

    def test_only_matching_numbered_long_names_are_valid(self):
        names=['uzun_trailer_999.mp4','uzun_video_8.mp4']
        table={n:meta(n) for n in names}
        self.assertEqual(self.select(table,[item(n) for n in names],kind='long')['name'],'uzun_video_8.mp4')

    def test_friday_1230_is_long_and_all_other_slots_are_short(self):
        tr=timezone(timedelta(hours=3))
        self.assertEqual(m.decide_prime_time_video_type(datetime(2026,10,30,12,30,tzinfo=tr)),'long')
        self.assertEqual(m.decide_prime_time_video_type(datetime(2026,10,30,19,30,tzinfo=tr)),'short')
        self.assertEqual(m.decide_prime_time_video_type(datetime(2026,10,29,12,30,tzinfo=tr)),'short')
        self.assertEqual(m.decide_prime_time_video_type(datetime(2026,10,29,19,30,tzinfo=tr)),'short')

    def test_old_and_already_published_files_rejected(self):
        for name in ['video_137.mp4','video_150.mp4','video_154.mp4','video_157.mp4','uzun_video_7.mp4','uzun_video_17.mp4']:
            self.assertTrue(m.is_skipped_by_floor(name),name)
        self.assertFalse(m.is_skipped_by_floor('video_155.mp4'))
        self.assertFalse(m.is_skipped_by_floor('uzun_video_8.mp4'))
        self.assertFalse(m.is_skipped_by_floor('uzun_video_18.mp4'))

    def test_duplicate_drive_files_fail_closed(self):
        files=[{'id':'a','name':'video_155.mp4','mimeType':'video/mp4'},
               {'id':'b','name':'VIDEO_155.MP4','mimeType':'video/mp4'},
               {'id':'c','name':'video_156.mp4','mimeType':'video/mp4'}]
        class Request:
            def execute(self): return {'files':files}
        class DriveFiles:
            def list(self,**kw): return Request()
        class Drive:
            def files(self): return DriveFiles()
        results,count=m.list_drive_videos_with_stats(Drive(),'queue')
        self.assertEqual(count,1)
        self.assertEqual([r['name'] for r in results],['video_156.mp4'])

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(ValueError): self.select({},[],kind='invalid')

    def test_watchdog_receives_schedule_context(self):
        from pathlib import Path
        text = (Path(__file__).resolve().parent.parent / '.github/workflows/slot-watchdog.yml').read_text(encoding='utf-8')
        self.assertIn("GITHUB_EVENT_SCHEDULE: ${{ github.event.schedule || '' }}", text)
        self.assertIn('os.environ.get("GITHUB_EVENT_SCHEDULE", "")', text)


if __name__ == '__main__':
    unittest.main()
