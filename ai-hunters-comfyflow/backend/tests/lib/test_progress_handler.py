import pytest
from unittest.mock import MagicMock, patch

# Adjust path to import the class from the parent directory
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from cb2c_py.lib.progress_handler import ComfyUIProgressHandler

@pytest.fixture
def mock_tqdm():
    """Fixture to mock the tqdm class."""
    with patch('cb2c_py.lib.progress_handler.tqdm') as mock_tqdm_class:
        # Mock the tqdm instance that the class will create
        mock_pbar_instance = MagicMock()
        mock_pbar_instance.n = 0
        mock_pbar_instance.total = 100
        mock_tqdm_class.return_value = mock_pbar_instance
        yield mock_tqdm_class, mock_pbar_instance

def test_initialization_with_name():
    """Tests initialization with a specific name."""
    handler = ComfyUIProgressHandler(name="Test Progress")
    assert handler.name == "Test Progress"
    assert handler.pbar is None
    assert handler.current_node_id is None

def test_initialization_default_name():
    """Tests initialization with the default name."""
    handler = ComfyUIProgressHandler()
    assert handler.name == "Workflow Progress"

def test_progress_message_creates_pbar(mock_tqdm):
    """Tests that the first progress message creates a new tqdm progress bar."""
    mock_tqdm_class, mock_pbar_instance = mock_tqdm
    handler = ComfyUIProgressHandler()
    
    message = {"type": "progress", "data": {"value": 10, "max": 100}}
    handler(message)
    
    mock_tqdm_class.assert_called_once_with(total=100, desc="Workflow Progress", unit="step")
    mock_pbar_instance.update.assert_called_once_with(10)

def test_progress_message_updates_existing_pbar(mock_tqdm):
    """Tests that subsequent progress messages update the existing pbar."""
    _, mock_pbar_instance = mock_tqdm
    handler = ComfyUIProgressHandler()

    # First message to create the bar
    handler(message={"type": "progress", "data": {"value": 10, "max": 100}})
    mock_pbar_instance.n = 10 # Simulate tqdm's internal state update
    
    # Second message
    handler(message={"type": "progress", "data": {"value": 25, "max": 100}})
    
    # Check that update was called with the difference
    mock_pbar_instance.update.assert_called_with(15) # 25 - 10

def test_executing_message_sets_node_id_and_closes_old_pbar(mock_tqdm):
    """Tests that an 'executing' message for a new node closes the old pbar and sets the new node ID."""
    _, mock_pbar_instance = mock_tqdm
    handler = ComfyUIProgressHandler()

    # Create an initial pbar for a previous node
    handler(message={"type": "progress", "data": {"value": 50, "max": 100}})
    mock_pbar_instance.n = 50
    
    # Message for a new node starting execution
    executing_message = {"type": "executing", "data": {"node": "123", "prompt_id": "abc"}}
    handler(executing_message)
    
    # The old pbar should be completed and closed.
    # The first call to update was from the progress message.
    # The second call is to fill the bar before closing.
    assert mock_pbar_instance.update.call_count == 2
    mock_pbar_instance.close.assert_called_once()
    
    # pbar should be reset, and node ID updated
    assert handler.pbar is None
    assert handler.current_node_id == "123"

def test_executing_message_with_no_active_pbar(mock_tqdm):
    """Tests that an 'executing' message doesn't fail if there's no active pbar."""
    _, mock_pbar_instance = mock_tqdm
    handler = ComfyUIProgressHandler()
    
    executing_message = {"type": "executing", "data": {"node": "123", "prompt_id": "abc"}}
    handler(executing_message)
    
    mock_pbar_instance.close.assert_not_called()
    assert handler.pbar is None
    assert handler.current_node_id == "123"

def test_executing_message_for_workflow_end(mock_tqdm):
    """Tests that an 'executing' message with node=None (end of workflow) closes the pbar."""
    _, mock_pbar_instance = mock_tqdm
    handler = ComfyUIProgressHandler()

    # A pbar is active
    handler(message={"type": "progress", "data": {"value": 50, "max": 100}})
    
    # Workflow finishes
    end_message = {"type": "executing", "data": {"node": None, "prompt_id": "abc"}}
    handler(end_message)
    
    mock_pbar_instance.close.assert_called_once()
    assert handler.pbar is None
    assert handler.current_node_id is None

def test_status_message_closes_pbar_on_queue_empty(mock_tqdm):
    """Tests that a 'status' message with queue_remaining=0 closes the active pbar."""
    _, mock_pbar_instance = mock_tqdm
    handler = ComfyUIProgressHandler()

    # A pbar is active
    handler(message={"type": "progress", "data": {"value": 30, "max": 100}})
    
    # Status message indicating the queue is now empty
    status_message = {"type": "status", "data": {"exec_info": {"queue_remaining": 0}}}
    handler(status_message)
    
    mock_pbar_instance.close.assert_called_once()
    assert handler.pbar is None

def test_other_message_types_are_ignored(mock_tqdm):
    """Tests that other message types do not cause errors or interactions."""
    mock_tqdm_class, mock_pbar_instance = mock_tqdm
    handler = ComfyUIProgressHandler()
    
    handler({"type": "some_other_type", "data": {}})
    
    mock_tqdm_class.assert_not_called()
    mock_pbar_instance.update.assert_not_called()
    mock_pbar_instance.close.assert_not_called()