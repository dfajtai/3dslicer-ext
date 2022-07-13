import os, sys
from numpy import source
import pandas as pd
import re
import numpy as np
import nibabel
import shutil
import glob


def initialize(source_folder, current_nas_path, target_nas_path, target_folder, etc_folder):
  assert os.path.exists(current_nas_path)
  assert os.path.exists(source_folder)
  assert os.path.exists(os.path.join(current_nas_path,etc_folder))

  os.makedirs(os.path.join(current_nas_path,target_folder),exist_ok=True)

  db_csv_path = os.path.join(current_nas_path,etc_folder,"database.csv")
  preseg_csv_path = os.path.join(current_nas_path,etc_folder,"img_paths.csv")

  db_df = pd.DataFrame()
  preseg_df = pd.DataFrame()

  sid_list = os.listdir(source_folder)
  sid_mask = r"^n[0-9]{3}"
  _mask = re.compile(sid_mask)
  sid_list = sorted(list(filter(lambda x: re.match(_mask,x),sid_list)))

  for sid in sid_list:
    print(sid)

    t1_path = glob.glob(os.path.join(source_folder,sid,"t1","l-*t1-1*nii*"))
    if len(t1_path)==0:
      print("t1 not found")
      continue
    t1_path = t1_path[0]


    pet_path = glob.glob(os.path.join(source_folder,sid,"pet","max_suv_bw*zb4*nii.gz"))
    if len(pet_path)==0:
      print("pet not found")
      continue
    pet_path = pet_path[0]

    mask_path = glob.glob(os.path.join(source_folder,sid,"pet","pre_liver_mask*nii.gz"))
    if len(mask_path) == 0:
      print("mask not found")
      continue
    mask_path = mask_path[0]
    spec_dir = os.path.join(current_nas_path,target_folder,sid,"pet")
    os.makedirs(spec_dir,exist_ok=True)
    _t1_path = os.path.join(spec_dir,os.path.basename(t1_path))
    shutil.copy(t1_path,_t1_path)
    _pet_path = os.path.join(spec_dir,os.path.basename(pet_path))
    shutil.copy(pet_path,_pet_path)
    _mask_path = os.path.join(spec_dir,os.path.basename(mask_path))
    shutil.copy(mask_path,_mask_path)

    preseg_df = preseg_df.append({"ID":sid,"t1":_t1_path.replace(current_nas_path,target_nas_path),
                                   "pet":_pet_path.replace(current_nas_path,target_nas_path),
                                   "mask":_mask_path.replace(current_nas_path,target_nas_path)},ignore_index=True)
    db_df = db_df.append({"ID":sid,"done":0} ,ignore_index = True)
  
  db_df["done"] = db_df["done"].astype(int)
  db_df = db_df[["ID","done"]]

  db_df.to_csv(db_csv_path,index=False)
  preseg_df.to_csv(preseg_csv_path,index=False)

if __name__ == "__main__":
  current_nas_path = "/nas/medicopus_share"
  target_nas_path = "Z:"
  # target_nas_path = "/nas/medicopus_share"
  source_folder = "/data/rabbit/"
  target_folder =  os.path.join("Projects","mycotoxin","segmentation") 
  etc_folder =  os.path.join("Projects","mycotoxin","etc")
  initialize( source_folder=source_folder,
    current_nas_path=current_nas_path,target_nas_path=target_nas_path, 
              target_folder=target_folder,
              etc_folder=etc_folder)
  pass
