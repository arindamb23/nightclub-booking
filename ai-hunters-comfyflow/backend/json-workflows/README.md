# ComfyUI JSON workflows (command-line converter)

Put ComfyUI workflow `.json` files here and run, from the `backend` folder:

    .venv\Scripts\python -m cb2c_py.tools.convert_workflow

Each file is converted to a Python script in `backend\user\workflows\` (use `-o` for another folder).
In the app you do not need this folder: *New workflow* converts a JSON file for you.
