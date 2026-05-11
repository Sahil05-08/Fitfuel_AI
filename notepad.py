from huggingface_hub import login, HfApi

# Token entered at runtime — never saved in file
token = input("Paste your HF token here: ")
login(token=token)

api = HfApi()
api.upload_folder(
    folder_path=".",
    repo_id="Sahil585/Fitness_Ai",
    repo_type="space",
    ignore_patterns=[
        ".env",
        "__pycache__/**",
        "*.pyc",
        "fitfuel_memory/**",
        "notepad.py",        
        "upload.py"
    ]
)

print("Upload complete!")