import shutil
free_bytes = shutil.disk_usage("C:\\").free
print(f"Free: {free_bytes:,} bytes = {free_bytes/1e9:.2f} GB")
