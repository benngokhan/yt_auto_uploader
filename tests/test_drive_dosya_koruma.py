import unittest
from unittest.mock import MagicMock
import uploader


class DriveDosyaKorumaTest(unittest.TestCase):
    def test_video_ve_kapaklar_hicbir_kosulda_cop_kutusuna_tasinmaz(self):
        for name in ('video_155.mp4', 'video_183.mp4', 'uzun_video_8.mp4'):
            drive = MagicMock()
            uploader._arsiv_temizle(drive, 'fake', name)
            drive.files.assert_not_called()

if __name__ == '__main__':
    unittest.main()
