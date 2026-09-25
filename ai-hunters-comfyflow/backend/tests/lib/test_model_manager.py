import pytest
import json
import requests
from unittest.mock import patch, mock_open, MagicMock

# Adjust path for imports
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from cb2c_py.lib.model_manager import ModelManager, _download_file, NODE_MODEL_WIDGET_MAP

# Sample models.json content for testing
MODELS_DB_CONTENT = {
    "checkpoints": ["https://example.com/models/checkpoint1.safetensors"],
    "loras": ["https://example.com/models/lora1.safetensors"],
    "vae": ["https://example.com/models/vae1.pt"]
}

# --- Fixtures ---
@pytest.fixture
def model_manager(tmp_path):
    """Fixture for a ModelManager instance with a temporary base directory."""
    db_path = tmp_path / "models.json"
    with open(db_path, "w") as f:
        json.dump(MODELS_DB_CONTENT, f)
    
    models_base_dir = tmp_path / "models"
    models_base_dir.mkdir()
    
    return ModelManager(str(db_path), str(models_base_dir))

@pytest.fixture
def mock_workflow():
    """Fixture for a mock workflow object."""
    workflow = MagicMock()
    
    # Mock nodes
    node1 = MagicMock()
    node1.original_name = "CheckpointLoaderSimple"
    node1.input_values = {"ckpt_name": "checkpoint1.safetensors"}
    
    node2 = MagicMock()
    node2.original_name = "LoraLoader"
    node2.input_values = {"lora_name": "lora1.safetensors"}
    
    node3 = MagicMock()
    node3.original_name = "SomeOtherNode" # A node that doesn't load models
    node3.input_values = {}

    node4 = MagicMock()
    node4.original_name = "CheckpointLoaderSimple"
    node4.input_values = {"ckpt_name": "missing_model.safetensors"} # A model not in our DB

    workflow.nodes = {"1": node1, "2": node2, "3": node3, "4": node4}
    return workflow

# --- Tests for ModelManager Class ---

def test_load_models_db_success(tmp_path):
    """Tests successful loading of the models database."""
    db_path = tmp_path / "models.json"
    with open(db_path, "w") as f:
        json.dump(MODELS_DB_CONTENT, f)
        
    manager = ModelManager(str(db_path), "dummy_dir")
    
    assert "checkpoint1.safetensors" in manager.models_db
    assert manager.models_db["checkpoint1.safetensors"]["category"] == "checkpoints"
    assert "lora1.safetensors" in manager.models_db
    assert manager.models_db["lora1.safetensors"]["url"] == "https://example.com/models/lora1.safetensors"

def test_load_models_db_not_found(capsys):
    """Tests behavior when the models.json file is not found."""
    manager = ModelManager("nonexistent_path.json", "dummy_dir")
    
    assert manager.models_db == {}
    captured = capsys.readouterr()
    assert "Models manifest not found" in captured.err

@patch('cb2c_py.lib.model_manager._download_file')
def test_check_and_download_model_found_locally(mock_download, model_manager, capsys):
    """Tests that download is skipped if the model exists locally."""
    model_filename = "checkpoint1.safetensors"
    model_info = model_manager.models_db[model_filename]
    
    # Create a dummy file to simulate it exists
    dest_dir = os.path.join(model_manager.models_base_dir, model_info["category"])
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, model_filename)
    with open(dest_path, "w") as f:
        f.write("dummy content")
        
    model_manager._check_and_download_model(model_filename)
    
    mock_download.assert_not_called()
    captured = capsys.readouterr()
    assert f"Model '{model_filename}' found. ✔️" in captured.out

@patch('cb2c_py.lib.model_manager._download_file')
def test_check_and_download_model_not_found_locally(mock_download, model_manager, capsys):
    """Tests that a model is downloaded if it's missing locally."""
    model_filename = "lora1.safetensors"
    model_info = model_manager.models_db[model_filename]
    dest_path = os.path.join(model_manager.models_base_dir, model_info["category"], model_filename)

    model_manager._check_and_download_model(model_filename)
    
    mock_download.assert_called_once_with(model_info["url"], dest_path)
    captured = capsys.readouterr()
    assert f"Model '{model_filename}' not found. Downloading..." in captured.out

def test_check_and_download_model_not_in_db(model_manager, capsys):
    """Tests the warning for a model not present in the database."""
    model_filename = "unknown_model.ckpt"
    model_manager._check_and_download_model(model_filename)
    
    captured = capsys.readouterr()
    assert f"Warning: Model '{model_filename}' not found in model db." in captured.err

@patch('cb2c_py.lib.model_manager.ModelManager._check_and_download_model')
def test_ensure_models_for_workflow(mock_check_and_download, model_manager, mock_workflow):
    """Tests the main entry point to ensure all models for a workflow are checked."""
    model_manager.ensure_models_for_workflow(mock_workflow)
    
    # It should be called for the two models present in the workflow
    mock_check_and_download.assert_any_call("checkpoint1.safetensors")
    mock_check_and_download.assert_any_call("lora1.safetensors")
    mock_check_and_download.assert_any_call("missing_model.safetensors")
    
    # Should be called 3 times (one for each loader node)
    assert mock_check_and_download.call_count == 3

# --- Tests for _download_file Helper Function ---

@patch('requests.get')
def test_download_file_success(mock_requests_get, tmp_path):
    """Tests a successful file download."""
    url = "https://example.com/file.zip"
    dest_path = tmp_path / "file.zip"
    
    # Mock the response from requests.get
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.headers.get.return_value = "16384" # 16 KB
    mock_response.iter_content.return_value = [b'chunk1' * 1024, b'chunk2' * 1024]
    mock_requests_get.return_value = mock_response
    
    # Mock open to check the write operations
    m = mock_open()
    with patch('builtins.open', m):
        _download_file(url, str(dest_path))

    mock_requests_get.assert_called_once_with(url, stream=True, allow_redirects=True)
    m.assert_called_once_with(str(dest_path), "wb")
    handle = m()
    handle.write.assert_any_call(b'chunk1' * 1024)
    handle.write.assert_any_call(b'chunk2' * 1024)

@patch('requests.get')
def test_download_file_request_exception(mock_requests_get, tmp_path):
    """Tests that an exception during download is handled and the partial file is cleaned up."""
    url = "https://example.com/invalid"
    dest_path = tmp_path / "partial.file"
    
    # Simulate a request exception
    mock_requests_get.side_effect = requests.exceptions.RequestException("Test error")
    
    # os.path.exists should return False first (so download is attempted),
    # then True (so cleanup can happen).
    with patch('os.path.exists', side_effect=[False, True]) as mock_exists, \
         patch('os.remove') as mock_remove:
        
        with pytest.raises(requests.exceptions.RequestException):
            _download_file(url, str(dest_path))
            
        # Check that we attempted to remove the partially downloaded file
        assert mock_exists.call_count == 2
        mock_remove.assert_called_once_with(str(dest_path))

def test_download_file_already_exists(tmp_path, capsys):
    """Tests that the download is skipped if the destination file already exists."""
    url = "https://example.com/exists.txt"
    dest_path = tmp_path / "exists.txt"
    dest_path.write_text("I already exist.")
    
    _download_file(url, str(dest_path))
    
    captured = capsys.readouterr()
    assert "exists.txt ✔️" in captured.out