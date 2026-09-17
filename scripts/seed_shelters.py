import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import SessionLocal, Shelter, ROS_PRIUT_INDEX

# Seed is intentionally metadata-first. Missing contacts are left NULL.
# source_url points to the public registry used to discover the entry.
DATA = [
('beskudnikovo','Приют Бескудниково','Москва','Москва','Лианозово, Проектируемый проезд №6453','https://dogpriut.ru/'),
('iskra','Приют Искра','Москва','Москва','ул. Искры, д. 23а','https://priutiskra.ru/'),
('dubovaya-roshcha','Приют Дубовая Роща','Москва','Москва','пр-д Дубовой рощи, д. 25А, стр. 4','https://priyut-ostankino.ru/'),
('krasnaya-sosna','Приют Красная Сосна','Москва','Москва','ул. Красная сосна, д. 30, стр. 7','https://priut-ks.ru/'),
('kozhukhovo','Приют Кожухово','Москва','Москва',None,None),
('pechatniki','Приют Печатники','Москва','Москва','Проектируемый пр-д №5112, стр. 1-3','https://pechatniki-pets.ru/'),
('biryulyovo','Приют Бирюлёво','Москва','Москва','Востряковский пр-д, д. 10А',None),
('shcherbinka','Приют Щербинка','Москва','Москва','ул. Брусилова, д. 32Б','https://mospriut.com/'),
('solntsevo','Приют Солнцево','Москва','Москва','ул. Родниковая, вл. 26',None),
('zelenograd','Приют Зеленоград','Москва','Зеленоград','Фирсановское ш., вл. 5А',None),
('nekrasovka','Приют Некрасовка','Москва','Москва','ул. 2-я Вольская, д. 17, стр. 3',None),
('zoorassvet','Приют Зоорассвет','Москва','Москва','Рассветная аллея, д. 10',None),
('pushistyi-drug','Приют Пушистый друг','Москва','Москва','пос. Краснопахорское, вблизи дер. Чириково','https://push-dryg.ru/'),
('iskry-street','Приют на ул. Искры','Москва','Москва','ул. Искры, д. 23а',None),
('krasnaya-sosna-street','Приют на ул. Красная Сосна','Москва','Москва','ул. Красная сосна, д. 30, стр. 7',None),
('vernye-druzya','Приют Верные друзья','Москва','Москва',None,None),
('murkosha','Муркоша','Москва','Москва','ул. Осташковская, д. 14, стр. 2','https://murkosha.ru/'),
('marikoshki','МариКошки','Москва','Москва',None,None),
('kotodom','КотоДом','Москва','Москва',None,None),
('eko','ЭКО','Москва','Москва',None,None),
('lesnoy-priyut','Лесной приют','Московская область','Истринский район',None,None),
('zov-predkov','Зов Предков','Московская область','Одинцовский г.о.','п.г.т. Большие Вязёмы, Западный проезд','https://zovpredkov.ru/'),
('veles','Велес','Московская область','Пушкинский г.о.','село Рахманово',None),
('yuna','Юна','Московская область','Подольск','дер. Кутьино, д. 64','https://yunacenter.ru/'),
('umka','Умка','Московская область','Дмитровский г.о.','дер. Надмошье',None),
('put-domoy','Путь домой','Московская область','Раменский муниципальный округ','с. Кривцы, ул. Мечты, рядом с д. 65',None),
('zoogorodok','Зоогородок','Московская область','г.о. Клин','дер. Вертково',None),
('lokhmaty-angel','Лохматый ангел','Московская область','Красногорск','коммунальная зона Красногорск-Митино','https://ecozoo.ru/'),
('ekologiya-cheloveka','Экология человека','Московская область','Одинцовский г.о.','дер. Малые Вязёмы','https://ecozoo.ru/'),
('kus','Кусь','Московская область','Рузский м.о.','д. Ивойлово',None),
('kotodom-murlyka','Котодом Мурлыка','Московская область','Балашиха','ул. Советская, д. 36, корп. 13','https://kotodommurlyka.ru/'),
('bim-hoteichi','Бим-Хотеичи','Московская область','Орехово-Зуевский округ',None,None),
('bim-degunino','Бим-Дегунино','Москва','Москва',None,None),
('bim-tomilino','Бим-Томилино','Московская область','Люберцы',None,None),
('bim-zhulebino','Бим-Жулебино','Москва','Москва',None,None),
('bim-otradnoe','Бим-Отрадное','Москва','Москва',None,None),
('v-dobrye-ruki','В Добрые Руки','Московская область','Химки','район Шереметьево-2','https://helpdog.ru/'),
('egorka','Егорка','Московская область','Егорьевск',None,None),
('zozashchita-plus','Зоозащита плюс','Московская область','Серпухов','ул. Чехова, 78','https://zoo-up.ru/'),
('domashniy','Домашний','Московская область','Ленинский г.о.','село Булатниково',None),
('beriginya','Беригиня','Московская область','Наро-Фоминский г.о.','дер. Скугорово',None),
]

with SessionLocal() as db:
    for sid, name, region, city, address, website in DATA:
        s = db.get(Shelter, sid)
        if not s:
            s = Shelter(id=sid, name=name, region=region, city=city, address=address,
                        website=website, source_url=ROS_PRIUT_INDEX, verified=False,
                        active=True, source_type='none', import_enabled=False,
                        status='active', animal_count=0)
            db.add(s)
        else:
            s.name=name; s.region=region; s.city=city; s.address=address; s.website=website
            if not s.source_url: s.source_url=ROS_PRIUT_INDEX
    db.commit()
print(f'Seeded {len(DATA)} unique shelters')
