import os, sys
from numpy import source
import pandas as pd
import re
import numpy as np
import nibabel
import shutil



def initialize(current_nas_path, target_nas_path, source_folder, target_folder, etc_folder):
  assert os.path.exists(current_nas_path)
  assert os.path.exists(os.path.join(current_nas_path,source_folder))
  assert os.path.exists(os.path.join(current_nas_path,etc_folder))

  os.makedirs(os.path.join(current_nas_path,target_folder),exist_ok=True)

  filename_mask = r"^[0-9]{3}[.]mnc-[fak][.]nii"  
  _mask = re.compile(filename_mask)

  files = os.listdir(os.path.join(current_nas_path,source_folder))
  filtered_files = sorted(list(filter(lambda x: re.match(_mask,x),files)))
  print(filtered_files)

  db_csv_path = os.path.join(current_nas_path,etc_folder,"rabbit_database.csv")
  preseg_csv_path = os.path.join(current_nas_path,etc_folder,"preseg_paths.csv")

  db_df = pd.DataFrame()
  preseg_df = pd.DataFrame()

  for f in filtered_files:
    num = str(f).split(".")[0]
    position = str(f).split("-")[1][0]
    _ID = f"{num}-{position}"
    print(_ID)
    spec_dir = os.path.join(current_nas_path,target_folder,_ID)
    os.makedirs(spec_dir,exist_ok=True)
    img_path = os.path.join(spec_dir,f)
    shutil.copy(os.path.join(current_nas_path,source_folder,f),img_path)
    hinds_path = os.path.join(spec_dir,f"{_ID}-hinds.nii.gz")
    mld_path = os.path.join(spec_dir,f"{_ID}-mld.nii.gz")

    I = nibabel.load(img_path)
    nibabel.save(nibabel.Nifti1Image(np.zeros_like(I.get_fdata()),I.affine),hinds_path)
    nibabel.save(nibabel.Nifti1Image(np.zeros_like(I.get_fdata()),I.affine),mld_path)

    preseg_df = preseg_df.append({"ID":_ID,"CT":img_path.replace(current_nas_path,target_nas_path),
                                   "hinds":hinds_path.replace(current_nas_path,target_nas_path),
                                   "mld": mld_path.replace(current_nas_path,target_nas_path)},ignore_index=True)
    db_df = db_df.append({"ID":_ID,"position":position, "done":0} ,ignore_index = True)
  
  db_df["done"] = db_df["done"].astype(int)
  db_df["mld_done"] = db_df["done"]
  db_df["hinds_done"] = db_df["done"]
  db_df = db_df[["ID","position","hinds_done","mld_done","done"]]

  db_df.to_csv(db_csv_path,index=False)
  preseg_df.to_csv(preseg_csv_path,index=False)

if __name__ == "__main__":
  current_nas_path = "/nas/medicopus_share"
  target_nas_path = "Z:"
  # target_nas_path = "/nas/medicopus_share"
  source_folder = os.path.join("Projects","hycole","atlas")
  target_folder =  os.path.join("Projects","hycole","segmentation") 
  etc_folder =  os.path.join("Projects","hycole","etc")
  initialize(current_nas_path=current_nas_path,target_nas_path=target_nas_path, 
              source_folder=source_folder, target_folder=target_folder,
              etc_folder=etc_folder)
  pass
