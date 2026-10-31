import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image
import thumbnail_design as design
import uploader


def request(result=None, error=None):
    obj = MagicMock()
    if error is not None:
        obj.execute.side_effect = error
    else:
        obj.execute.return_value = result or {}
    return obj


class FakeFiles:
    def __init__(self, items=None, fail_create=False):
        self.items = items or []
        self.fail_create = fail_create
        self.created = []
        self.queries = []
    def list(self, **kwargs):
        q=kwargs['q'];self.queries.append(q)
        if "mimeType='application/vnd.google-apps.folder'" in q:
            return request({'files':[{'id':'covers','name':'KAPAKLAR'}]})
        if "'covers' in parents" in q:
            return request({'files':self.items})
        return request({'files':[]})
    def create(self, **kwargs):
        self.created.append(kwargs)
        if self.fail_create:return request(error=RuntimeError('Drive is unavailable'))
        return request({'id':'new-cover','name':kwargs['body']['name']})


class CoverDesignTests(unittest.TestCase):
    def test_turkish_i_hashtags_emoji_and_wrapping(self):
        lines = design.headline_lines('İlk yudum su daha kana karışmadan susuzluğu nasıl keser? 💧 #shorts')
        self.assertIn('İLK',lines[0]);self.assertNotIn('#',' '.join(lines))
        self.assertNotIn('💧',' '.join(lines));self.assertLessEqual(len(lines),3)
        self.assertEqual(design.tr_upper('i ı ş ğ ö ü ç'), 'İ I Ş Ğ Ö Ü Ç')
    def test_empty_title_is_not_replaced_with_misleading_text(self):
        with self.assertRaises(ValueError):design.headline_lines('💧 #shorts')
    def test_existing_frame_can_be_laid_out_in_both_youtube_aspects(self):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/'frame.jpg'
            Image.new('RGB',(400,710),(4,40,48)).save(src)
            for short,size in ((True,(1080,1920)),(False,(1280,720))):
                out=Path(td)/f'{short}.jpg'
                design.render_from_frame(src,out,'Güneşe bakınca neden hapşırırız? #shorts',short)
                with Image.open(out) as result:
                    self.assertEqual(result.size,size)
                    self.assertEqual(result.format,'JPEG')
                self.assertLess(out.stat().st_size,2_000_000)
    def test_ffmpeg_timeout_or_failure_cannot_fall_through_to_a_cover(self):
        with tempfile.TemporaryDirectory() as td:
            fake=Path(td)/'video.mp4';fake.write_bytes(b'not a video')
            out=Path(td)/'cover.jpg'
            with patch('thumbnail_design.ffmpeg_binary',return_value='ffmpeg'), \
                 patch('thumbnail_design.subprocess.run',side_effect=TimeoutError('timeout')):
                with self.assertRaises(TimeoutError):design.make_video_cover(fake,out,'Başlık',True)
            self.assertFalse(out.exists())


class CoverUploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.image=Path(self.tmp.name)/'fixture.jpg'
        Image.new('RGB',(108,192),(10,20,30)).save(self.image)
        self.youtube=MagicMock()
        self.youtube.thumbnails.return_value.set.return_value.execute.return_value={'kind':'thumbnail'}
        self.drive=MagicMock()
    def set_files(self,items=None,fail_create=False):
        files=FakeFiles(items,fail_create)
        self.drive.files.return_value=files
        return files
    def copy_fake_cover(self,drive,id,path):
        shutil.copyfile(self.image,path)
    def fake_frame_cover(self,video_path,dest,title,is_short):
        shutil.copyfile(self.image,dest)
    def media(self,*args,**kwargs):
        return ('fake-media',args[0],kwargs.get('mimetype'))
    def test_names_are_exact_and_short_long_are_not_confused(self):
        short,names,new=uploader.thumbnail_candidates('video_152.mp4')
        self.assertTrue(short);self.assertIn('kapak_152.jpg',names);self.assertEqual(new,'kapak_152.jpg')
        long,names,new=uploader.thumbnail_candidates('uzun_video_19.mp4')
        self.assertFalse(long);self.assertIn('uzun_kapak_19.png',names)
        self.assertNotIn('kapak_19.png',names)
        self.assertEqual(uploader.thumbnail_candidates('../video_152.mp4')[1],[])
    def test_existing_matched_short_is_sent_without_regeneration(self):
        files=self.set_files([{'id':'asset','name':'kapak_152.jpg','mimeType':'image/jpeg','size':'300'}])
        with patch.object(uploader,'download_drive_file',side_effect=self.copy_fake_cover) as download, \
             patch.object(uploader,'MediaFileUpload',side_effect=self.media), \
             patch('thumbnail_design.make_video_cover') as renderer:
            ok=uploader.upload_thumbnail_if_exists(self.youtube,self.drive,'queue','video_152.mp4','newvid',self.image,'Su')
        self.assertTrue(ok);download.assert_called_once();renderer.assert_not_called()
        self.youtube.thumbnails.return_value.set.assert_called_once()
        self.assertEqual(self.youtube.thumbnails.return_value.set.call_args.kwargs['videoId'],'newvid')
        self.assertEqual(files.created,[])
    def test_existing_long_png_keeps_compatibility(self):
        # The test bytes are PNG as well as the filename.
        self.image=Path(self.tmp.name)/'fixture.png';Image.new('RGB',(160,90)).save(self.image)
        self.set_files([{'id':'asset','name':'uzun_kapak_19.png','mimeType':'image/png','size':'300'}])
        with patch.object(uploader,'download_drive_file',side_effect=self.copy_fake_cover), \
             patch.object(uploader,'MediaFileUpload',side_effect=self.media):
            self.assertTrue(uploader.upload_thumbnail_if_exists(self.youtube,self.drive,'queue','uzun_video_19.mp4','longid'))
    def test_missing_cover_uses_only_new_video_and_is_saved_in_drive(self):
        files=self.set_files()
        with patch.object(uploader,'MediaFileUpload',side_effect=self.media), \
             patch('thumbnail_design.make_video_cover',side_effect=self.fake_frame_cover) as renderer:
            ok=uploader.upload_thumbnail_if_exists(self.youtube,self.drive,'queue','video_152.mp4','newvid',self.image,'Susuzluk')
        self.assertTrue(ok);renderer.assert_called_once()
        self.assertEqual(renderer.call_args.args[0],self.image)
        self.assertEqual(files.created[0]['body']['name'],'kapak_152.jpg')
        self.assertEqual(files.created[0]['body']['parents'],['covers'])
        self.assertEqual(self.youtube.thumbnails.return_value.set.call_args.kwargs['videoId'],'newvid')
    def test_youtube_rejection_does_not_raise_or_erase_drive_cover(self):
        files=self.set_files()
        self.youtube.thumbnails.return_value.set.return_value.execute.side_effect=RuntimeError('Shorts unsupported')
        with patch.object(uploader,'MediaFileUpload',side_effect=self.media), \
             patch('thumbnail_design.make_video_cover',side_effect=self.fake_frame_cover):
            result=uploader.upload_thumbnail_if_exists(self.youtube,self.drive,'queue','video_152.mp4','newvid',self.image,'Su')
            self.assertFalse(result)
            self.assertTrue(result.drive_saved)
        self.assertEqual(len(files.created),1)
    def test_drive_write_failure_does_not_prevent_youtube_attempt(self):
        self.set_files(fail_create=True)
        with patch.object(uploader,'MediaFileUpload',side_effect=self.media), \
             patch('thumbnail_design.make_video_cover',side_effect=self.fake_frame_cover):
            result=uploader.upload_thumbnail_if_exists(self.youtube,self.drive,'queue','video_152.mp4','newvid',self.image,'Su')
            self.assertTrue(result)
            self.assertFalse(result.drive_saved)
        self.youtube.thumbnails.return_value.set.assert_called_once()
    def test_wrong_aspect_is_not_sent_to_youtube(self):
        self.image=Path(self.tmp.name)/'horizontal.jpg';Image.new('RGB',(160,90)).save(self.image)
        self.set_files([{'id':'asset','name':'kapak_152.jpg','mimeType':'image/jpeg','size':'300'}])
        with patch.object(uploader,'download_drive_file',side_effect=self.copy_fake_cover), \
             patch.object(uploader,'MediaFileUpload',side_effect=self.media):
            result=uploader.upload_thumbnail_if_exists(self.youtube,self.drive,'queue','video_152.mp4','newvid',self.image,'Su')
        self.assertFalse(result)
        self.youtube.thumbnails.return_value.set.assert_not_called()
    def test_duplicate_exact_cover_names_fail_closed(self):
        self.set_files([{'id':'asset1','name':'kapak_152.jpg','mimeType':'image/jpeg'},
                        {'id':'asset2','name':'kapak_152.jpg','mimeType':'image/jpeg'}])
        with patch.object(uploader,'download_drive_file') as download:
            self.assertFalse(uploader.upload_thumbnail_if_exists(self.youtube,self.drive,'queue','video_152.mp4','newvid',self.image,'Su'))
        download.assert_not_called()
        self.youtube.thumbnails.return_value.set.assert_not_called()
    def test_report_distinguishes_drive_from_youtube_and_does_not_claim_shorts_display(self):
        from unittest.mock import patch
        import os
        with patch.object(uploader,'load_table_from_drive_or_local',side_effect=RuntimeError()), \
             patch.dict(os.environ,{'GITHUB_EVENT_NAME':'push'}):
            msg=uploader.build_telegram_report('video_152.mp4','abc','https://youtu.be/abc',{'title':'Su'},False,
                                               thumbnail_ok=False,thumbnail_saved=True)
            self.assertIn('Drive',msg)
            self.assertIn('otomatik uygulama tamamlanmadı',msg)
            msg=uploader.build_telegram_report('video_152.mp4','abc','https://youtu.be/abc',{'title':'Su'},False,
                                               thumbnail_ok=True,thumbnail_saved=False)
            self.assertIn('Drive\'a kaydedilemedi',msg)
            self.assertIn('Shorts görünümünü Studio',msg)
    def test_render_failure_and_missing_cover_are_nonfatal(self):
        self.set_files()
        with patch('thumbnail_design.make_video_cover',side_effect=RuntimeError('ffmpeg down')):
            self.assertFalse(uploader.upload_thumbnail_if_exists(self.youtube,self.drive,'queue','video_152.mp4','newvid',self.image,'Su'))
        self.youtube.thumbnails.return_value.set.assert_not_called()
    def test_no_retroactive_131_thumbnail_heal_in_publish_job(self):
        src=(Path(uploader.__file__).read_text(encoding='utf-8'))
        job=src[src.index('def upload_job('):src.index('def ',src.index('def upload_job(')+10)]
        self.assertNotIn('MOxaXPkS0zw',job)
        self.assertIn('video_path=tmp_path, video_title=meta',job)
        self.assertLess(job.index('mark_as_uploaded('),job.index('upload_thumbnail_if_exists('))

if __name__=='__main__':unittest.main()
