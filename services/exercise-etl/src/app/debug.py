from src.app.ETL.extractor import Extractor
from src.app.ETL.load import loader
from src.app.ETL.load_creator import load_creator
from src.data.loader import load_json, save_json

user_data = Extractor().get_exercises()

file_name = "30_day_sample.json"

save_json(filename=file_name, load=user_data)

thirty_day = load_json(filename=file_name)
upload = loader()
table_name = "exercise_data"
upload.exists(table_name=table_name)

for data in thirty_day:
    load = load_creator(response=data).create_load()
    result = upload.add_record(load=load)

print("Done")
