"""One manually source-grounded script for a non-publishing renderer diagnostic.

This is NOT an automatically generated script or production-quality validation.
Source reviewed: https://van.physics.illinois.edu/ask/listing/27883
"""
from shorts_acceptance import validate_script


def candidate(topic):
    if topic != 'Mum üflendiğinde neden söner?':
        raise ValueError('Sabit deneme metni yalnız mum testine uygundur')
    lines = [
        'Mum alevi üflendiğinde neden birden sönüyor, hiç düşündün mü?',
        'Üflemek mum alevinin çevresindeki sıcak gazları hızla soğutur.',
        'Aynı hava akımı yanan balmumu buharını da dağıtır.',
        'Yeterli ısı ve yakıt kalmayınca yanma süreci durur.',
        'Peki mum alevi hangi koşullarda yeniden yanabilir?',
    ]
    title='Mum üflendiğinde neden söner?'
    cover=['MUM ÜFLENİNCE','NEDEN SÖNER?']
    validate_script([{'ses':x} for x in lines],topic=topic,title=title,cover_lines=cover,loop_anchor='mum')
    labels=[('?', 'MUM ALEVİ', 'NEDEN SÖNER?'),('!', 'SICAK GAZLAR', 'SOĞUR'),
            ('▼','BALMUMU BUHARI','DAĞILIR'),('⚡','ISI VE YAKIT','AZALIR'),('?', 'MUM ALEVİ','NEDEN SÖNER?')]
    rows=[{'ses':line,'ikon':icon,'baslik1':a,'baslik2':b,'kaynak':''} for line,(icon,a,b) in zip(lines,labels)]
    rows[0]['_v2_metadata']={'title_question':title,'cover_lines':cover,'loop_anchor':'mum','source_url':'',
                              'topic_filter':{'score':100,'accepted':True,'manually_prepared_preview':True}}
    return rows
