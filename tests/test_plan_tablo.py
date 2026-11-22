import io, unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from openpyxl import Workbook, load_workbook
from plan_tablo import mark_scheduled

class SheetPlanTests(unittest.TestCase):
    def setUp(self):
        wb=Workbook(); ws=wb.active;ws.title='DRIVE';ws.cell(2,2).value='video_183.mp4';ws.cell(2,3).value='Korunacak bilgi'
        other=wb.create_sheet('Başka');other['A1']='dokunma'
        buf=io.BytesIO();wb.save(buf);self.source=buf.getvalue();self.drive=MagicMock()
        self.drive.files().get().execute.side_effect=[{'modifiedTime':'same'},{'modifiedTime':'same'}]
        self.slot=datetime(2026,11,22,16,30,tzinfo=timezone.utc)
    def execute(self):
        data=self.source
        class Download:
            def __init__(self,buf,req):buf.write(data)
            def next_chunk(self):return None,True
        with patch('plan_tablo.MediaIoBaseDownload',Download),patch('plan_tablo.MediaIoBaseUpload',side_effect=lambda b,**kw:b.getvalue()):
            mark_scheduled(self.drive,'video_183.mp4','https://youtu.be/fake',self.slot)
    def test_only_expected_row_changes(self):
        self.execute(); raw=self.drive.files().update.call_args.kwargs['media_body'];wb=load_workbook(io.BytesIO(raw))
        self.assertEqual(wb['DRIVE']['A2'].value,'PLANLANDI');self.assertEqual(wb['DRIVE']['K2'].value,'2026-11-22 19:30 (Planlandı)')
        self.assertEqual(wb['DRIVE']['C2'].value,'Korunacak bilgi');self.assertEqual(wb['Başka']['A1'].value,'dokunma')
    def test_concurrent_change_is_not_overwritten(self):
        self.drive.files().get().execute.side_effect=[{'modifiedTime':'a'},{'modifiedTime':'b'}]
        with self.assertRaisesRegex(RuntimeError,'eşzamanlı'):self.execute()
        self.drive.files().update.assert_not_called()
    def test_missing_video_no_write(self):
        wb=Workbook();wb.active.title='DRIVE';buf=io.BytesIO();wb.save(buf);self.source=buf.getvalue()
        with self.assertRaisesRegex(RuntimeError,'tekil'):self.execute()
        self.drive.files().update.assert_not_called()

if __name__=='__main__':unittest.main()
