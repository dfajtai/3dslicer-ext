import SimpleITK as sitk

# dtype handling

dtype_labels=[
  "uint8_t",
  "int8_t",
  "int16_t",
  "uint16_t",
  "int32_t",
  "uint32_t",
  "float",
  "double"]

dtype_values=[
  sitk.sitkUInt8,
  sitk.sitkInt8,
  sitk.sitkInt16,
  sitk.sitkUInt16,
  sitk.sitkInt32,
  sitk.sitkUInt32,
  sitk.sitkFloat32,
  sitk.sitkFloat64]

dtype_label_dict = dict(zip(dtype_labels,dtype_values))
dtype_label_reverse_dict = dict(zip(dtype_values,dtype_labels))

def reverse_lookup_dtype(dytpe, return_index = False):
  if return_index:
    if dytpe in dtype_values:
      return dtype_values.index(dytpe)
    return None
  else:
    return dtype_label_reverse_dict.get(dytpe)


def lookup_dtype(label, return_index = False):
  if return_index:
    if label in dtype_labels:
      return dtype_labels.index(label)
    return None
  else:
    return dtype_label_dict.get(label)