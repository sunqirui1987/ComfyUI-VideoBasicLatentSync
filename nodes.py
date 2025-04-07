import os
import tempfile
import torchaudio
import uuid
import sys
import shutil
from collections.abc import Mapping
import datetime

# Function to find ComfyUI directories
def get_comfyui_temp_dir():
    """Dynamically find the ComfyUI temp directory"""
    # First check using folder_paths if available
    try:
        import folder_paths
        comfy_dir = os.path.dirname(os.path.dirname(os.path.abspath(folder_paths.__file__)))
        temp_dir = os.path.join(comfy_dir, "temp")
        return temp_dir
    except:
        pass
    
    # Try to locate based on current script location
    try:
        # This script is likely in a ComfyUI custom nodes directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Go up until we find the ComfyUI directory
        potential_dir = current_dir
        for _ in range(5):  # Limit to 5 levels up
            if os.path.exists(os.path.join(potential_dir, "comfy.py")):
                return os.path.join(potential_dir, "temp")
            potential_dir = os.path.dirname(potential_dir)
    except:
        pass
    
    # Return None if we can't find it
    return None

# Function to clean up any ComfyUI temp directories
def cleanup_comfyui_temp_directories():
    """Find and clean up any ComfyUI temp directories"""
    comfyui_temp = get_comfyui_temp_dir()
    if not comfyui_temp:
        print("Could not locate ComfyUI temp directory")
        return
    
    comfyui_base = os.path.dirname(comfyui_temp)
    
    # Check for the main temp directory
    if os.path.exists(comfyui_temp):
        try:
            shutil.rmtree(comfyui_temp)
            print(f"Removed ComfyUI temp directory: {comfyui_temp}")
        except Exception as e:
            print(f"Could not remove {comfyui_temp}: {str(e)}")
            # If we can't remove it, try to rename it
            try:
                backup_name = f"{comfyui_temp}_backup_{uuid.uuid4().hex[:8]}"
                os.rename(comfyui_temp, backup_name)
                print(f"Renamed {comfyui_temp} to {backup_name}")
            except:
                pass
    
    # Find and clean up any backup temp directories
    try:
        all_directories = [d for d in os.listdir(comfyui_base) if os.path.isdir(os.path.join(comfyui_base, d))]
        for dirname in all_directories:
            if dirname.startswith("temp_backup_"):
                backup_path = os.path.join(comfyui_base, dirname)
                try:
                    shutil.rmtree(backup_path)
                    print(f"Removed backup temp directory: {backup_path}")
                except Exception as e:
                    print(f"Could not remove backup dir {backup_path}: {str(e)}")
    except Exception as e:
        print(f"Error cleaning up temp directories: {str(e)}")

# Create a module-level function to set up system-wide temp directory
def init_temp_directories():
    """Initialize global temporary directory settings"""
    # First clean up any existing temp directories
    cleanup_comfyui_temp_directories()
    
    # Generate a unique base directory for this module
    system_temp = tempfile.gettempdir()
    unique_id = str(uuid.uuid4())[:8]
    temp_base_path = os.path.join(system_temp, f"latentsync_{unique_id}")
    os.makedirs(temp_base_path, exist_ok=True)
    
    # Override environment variables that control temp directories
    os.environ['TMPDIR'] = temp_base_path
    os.environ['TEMP'] = temp_base_path
    os.environ['TMP'] = temp_base_path
    
    # Force Python's tempfile module to use our directory
    tempfile.tempdir = temp_base_path
    
    # Final check for ComfyUI temp directory
    comfyui_temp = get_comfyui_temp_dir()
    if comfyui_temp and os.path.exists(comfyui_temp):
        try:
            shutil.rmtree(comfyui_temp)
            print(f"Removed ComfyUI temp directory: {comfyui_temp}")
        except Exception as e:
            print(f"Could not remove {comfyui_temp}, trying to rename: {str(e)}")
            try:
                backup_name = f"{comfyui_temp}_backup_{unique_id}"
                os.rename(comfyui_temp, backup_name)
                print(f"Renamed {comfyui_temp} to {backup_name}")
                # Try to remove the renamed directory as well
                try:
                    shutil.rmtree(backup_name)
                    print(f"Removed renamed temp directory: {backup_name}")
                except:
                    pass
            except:
                print(f"Failed to rename {comfyui_temp}")
    
    print(f"Set up system temp directory: {temp_base_path}")
    return temp_base_path

# Function to clean up everything when the module exits
def module_cleanup():
    """Clean up all resources when the module is unloaded"""
    global MODULE_TEMP_DIR
    
    # Clean up our module temp directory
    if MODULE_TEMP_DIR and os.path.exists(MODULE_TEMP_DIR):
        try:
            shutil.rmtree(MODULE_TEMP_DIR, ignore_errors=True)
            print(f"Cleaned up module temp directory: {MODULE_TEMP_DIR}")
        except:
            pass
    
    # Do a final sweep for any ComfyUI temp directories
    cleanup_comfyui_temp_directories()

# Call this before anything else
MODULE_TEMP_DIR = init_temp_directories()

# Register the cleanup handler to run when Python exits
import atexit
atexit.register(module_cleanup)

# Now import regular dependencies
import math
import torch
import random
import torchaudio
import folder_paths
import numpy as np
import platform
import subprocess
import importlib.util
import importlib.machinery
import argparse
from omegaconf import OmegaConf
from PIL import Image
from decimal import Decimal, ROUND_UP
import requests

# Modify folder_paths module to use our temp directory
if hasattr(folder_paths, "get_temp_directory"):
    original_get_temp = folder_paths.get_temp_directory
    folder_paths.get_temp_directory = lambda: MODULE_TEMP_DIR
else:
    # Add the function if it doesn't exist
    setattr(folder_paths, 'get_temp_directory', lambda: MODULE_TEMP_DIR)

def import_inference_script(script_path):
    """Import a Python file as a module using its file path."""
    if not os.path.exists(script_path):
        raise ImportError(f"Script not found: {script_path}")

    module_name = "latentsync_inference"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None:
        raise ImportError(f"Failed to create module spec for {script_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)
    except Exception as e:
        del sys.modules[module_name]
        raise ImportError(f"Failed to execute module: {str(e)}")

    return module

def check_ffmpeg():
    try:
        if platform.system() == "Windows":
            # Check if ffmpeg exists in PATH
            ffmpeg_path = shutil.which("ffmpeg.exe")
            if ffmpeg_path is None:
                # Look for ffmpeg in common locations
                possible_paths = [
                    os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "ffmpeg", "bin"),
                    os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "ffmpeg", "bin"),
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg", "bin"),
                ]
                for path in possible_paths:
                    if os.path.exists(os.path.join(path, "ffmpeg.exe")):
                        # Add to PATH
                        os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
                        return True
                print("FFmpeg not found. Please install FFmpeg and add it to PATH")
                return False
            return True
        else:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
            return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("FFmpeg not found. Please install FFmpeg")
        return False

def check_and_install_dependencies():
    if not check_ffmpeg():
        raise RuntimeError("FFmpeg is required but not found")

    required_packages = [
        'omegaconf',
        'pytorch_lightning',
        'transformers',
        'accelerate',
        'huggingface_hub',
        'einops',
        'diffusers',
        'ffmpeg-python' 
    ]

    def is_package_installed(package_name):
        return importlib.util.find_spec(package_name) is not None

    def install_package(package):
        python_exe = sys.executable
        try:
            subprocess.check_call([python_exe, '-m', 'pip', 'install', package],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            print(f"Successfully installed {package}")
        except subprocess.CalledProcessError as e:
            print(f"Error installing {package}: {str(e)}")
            raise RuntimeError(f"Failed to install required package: {package}")

    for package in required_packages:
        if not is_package_installed(package):
            print(f"Installing required package: {package}")
            try:
                install_package(package)
            except Exception as e:
                print(f"Warning: Failed to install {package}: {str(e)}")
                raise

def normalize_path(path):
    """Normalize path to handle spaces and special characters"""
    return os.path.normpath(path).replace('\\', '/')

def get_ext_dir(subpath=None, mkdir=False):
    """Get extension directory path, optionally with a subpath"""
    # Get the directory containing this script
    dir = os.path.dirname(os.path.abspath(__file__))
    
    # Special case for temp directories
    if subpath and ("temp" in subpath.lower() or "tmp" in subpath.lower()):
        # Use our global temp directory instead
        global MODULE_TEMP_DIR
        sub_temp = os.path.join(MODULE_TEMP_DIR, subpath)
        if mkdir and not os.path.exists(sub_temp):
            os.makedirs(sub_temp, exist_ok=True)
        return sub_temp
    
    if subpath is not None:
        dir = os.path.join(dir, subpath)

    if mkdir and not os.path.exists(dir):
        os.makedirs(dir, exist_ok=True)
    
    return dir

def download_model(url, save_path):
    """Download a model from a URL and save it to the specified path."""
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    response = requests.get(url, stream=True)
    with open(save_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

def pre_download_models():
    """Pre-download all required models."""
    models = {
        "s3fd-e19a316812.pth": "https://www.adrianbulat.com/downloads/python-fan/s3fd-e19a316812.pth",
        # Add other models here
    }

    cache_dir = os.path.join(MODULE_TEMP_DIR, "model_cache")
    os.makedirs(cache_dir, exist_ok=True)
    
    for model_name, url in models.items():
        save_path = os.path.join(cache_dir, model_name)
        if not os.path.exists(save_path):
            print(f"Downloading {model_name}...")
            download_model(url, save_path)
        else:
            print(f"{model_name} already exists in cache.")

def setup_models():
    """Setup and pre-download all required models."""
    # Use our global temp directory
    global MODULE_TEMP_DIR
    
    # Pre-download additional models
    pre_download_models()

    # Existing setup logic for LatentSync models
    cur_dir = get_ext_dir()
    ckpt_dir = os.path.join(cur_dir, "checkpoints")
    whisper_dir = os.path.join(ckpt_dir, "whisper")
    os.makedirs(ckpt_dir, exist_ok=True)
    os.makedirs(whisper_dir, exist_ok=True)

    # Create a temp_downloads directory in our system temp
    temp_downloads = os.path.join(MODULE_TEMP_DIR, "downloads")
    os.makedirs(temp_downloads, exist_ok=True)
    
    unet_path = os.path.join(ckpt_dir, "latentsync_unet.pt")
    whisper_path = os.path.join(whisper_dir, "tiny.pt")

    if not (os.path.exists(unet_path) and os.path.exists(whisper_path)):
        print("Downloading required model checkpoints... This may take a while.")
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(repo_id="ByteDance/LatentSync-1.5",
                             allow_patterns=["latentsync_unet.pt", "whisper/tiny.pt"],
                             local_dir=ckpt_dir, 
                             local_dir_use_symlinks=False,
                             cache_dir=temp_downloads)
            print("Model checkpoints downloaded successfully!")
        except Exception as e:
            print(f"Error downloading models: {str(e)}")
            print("\nPlease download models manually:")
            print("1. Visit: https://huggingface.co/chunyu-li/LatentSync")
            print("2. Download: latentsync_unet.pt and whisper/tiny.pt")
            print(f"3. Place them in: {ckpt_dir}")
            print(f"   with whisper/tiny.pt in: {whisper_dir}")
            raise RuntimeError("Model download failed. See instructions above.")

class VideoBasicLatentSyncNode:
    def __init__(self):
        # Make sure our temp directory is the current one
        global MODULE_TEMP_DIR
        if not os.path.exists(MODULE_TEMP_DIR):
            os.makedirs(MODULE_TEMP_DIR, exist_ok=True)
        
        # Ensure ComfyUI temp doesn't exist
        comfyui_temp = get_comfyui_temp_dir()
        if comfyui_temp and os.path.exists(comfyui_temp):
            backup_name = f"{comfyui_temp}_backup_{uuid.uuid4().hex[:8]}"
            try:
                os.rename(comfyui_temp, backup_name)
            except:
                pass
        
        check_and_install_dependencies()
        setup_models()

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
                    "video_path": ("STRING", {"default": ""}),
                    "audio_path": ("STRING", {"default": ""}),
                    "seed": ("INT", {"default": 1247}),
                    "lips_expression": ("FLOAT", {"default": 1.5, "min": 1.0, "max": 3.0, "step": 0.1}),
                    "inference_steps": ("INT", {"default": 20, "min": 1, "max": 999, "step": 1}),
                 },}

    CATEGORY = "LatentSyncNode"

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_path",) 
    FUNCTION = "inference"

    def process_batch(self, batch, use_mixed_precision=False):
        with torch.cuda.amp.autocast(enabled=use_mixed_precision):
            processed_batch = batch.float() / 255.0
            if len(processed_batch.shape) == 3:
                processed_batch = processed_batch.unsqueeze(0)
            if processed_batch.shape[0] == 3:
                processed_batch = processed_batch.permute(1, 2, 0)
            if processed_batch.shape[-1] == 4:
                processed_batch = processed_batch[..., :3]
            return processed_batch

    def inference(self, video_path, audio_path, seed, lips_expression=1.5, inference_steps=20):
        # Use our module temp directory
        global MODULE_TEMP_DIR
        
        # Validate input paths
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Input video file not found: {video_path}")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Input audio file not found: {audio_path}")
        
        # Get GPU capabilities and memory
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        BATCH_SIZE = 4
        use_mixed_precision = False
        if torch.cuda.is_available():
            gpu_mem = torch.cuda.get_device_properties(0).total_memory
            # Convert to GB
            gpu_mem_gb = gpu_mem / (1024 ** 3)

            # Dynamically adjust batch size based on GPU memory
            if gpu_mem_gb > 20:  # High-end GPUs
                BATCH_SIZE = 32
                enable_tf32 = True
                use_mixed_precision = True
            elif gpu_mem_gb > 8:  # Mid-range GPUs
                BATCH_SIZE = 16
                enable_tf32 = False
                use_mixed_precision = True
            else:  # Lower-end GPUs
                BATCH_SIZE = 8
                enable_tf32 = False
                use_mixed_precision = False

            # Set performance options based on GPU capability
            torch.backends.cudnn.benchmark = True
            if enable_tf32:
                torch.backends.cuda.matmul.allow_tf32 = True
                torch.backends.cudnn.allow_tf32 = True

            # Clear GPU cache before processing
            torch.cuda.empty_cache()
            torch.cuda.set_per_process_memory_fraction(0.8)

        # Create a run-specific subdirectory in our temp directory
        run_id = ''.join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(5))
        temp_dir = os.path.join(MODULE_TEMP_DIR, f"run_{run_id}")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Ensure ComfyUI temp doesn't exist again (in case something recreated it)
        comfyui_temp = get_comfyui_temp_dir()
        if comfyui_temp and os.path.exists(comfyui_temp):
            backup_name = f"{comfyui_temp}_backup_{uuid.uuid4().hex[:8]}"
            try:
                os.rename(comfyui_temp, backup_name)
            except:
                pass
        
        output_video_path = None

        try:
            # Create output video path in our system temp directory
            output_video_path = os.path.join(temp_dir, f"latentsync_{run_id}_out.mp4")
            
            # Get the extension directory
            cur_dir = os.path.dirname(os.path.abspath(__file__))
            
            # Define paths to required files and configs
            inference_script_path = os.path.join(cur_dir, "scripts", "inference.py")
            config_path = os.path.join(cur_dir, "configs", "unet", "stage2.yaml")
            scheduler_config_path = os.path.join(cur_dir, "configs")
            ckpt_path = os.path.join(cur_dir, "checkpoints", "latentsync_unet.pt")
            whisper_ckpt_path = os.path.join(cur_dir, "checkpoints", "whisper", "tiny.pt")

            # Create config and args
            config = OmegaConf.load(config_path)

            # Set the correct mask image path
            mask_image_path = os.path.join(cur_dir, "latentsync", "utils", "mask.png")
            # Make sure the mask image exists
            if not os.path.exists(mask_image_path):
                # Try to find it in the utils directory directly
                alt_mask_path = os.path.join(cur_dir, "utils", "mask.png")
                if os.path.exists(alt_mask_path):
                    mask_image_path = alt_mask_path
                else:
                    print(f"Warning: Could not find mask image at expected locations")

            # Set mask path in config
            if hasattr(config, "data") and hasattr(config.data, "mask_image_path"):
                config.data.mask_image_path = mask_image_path

            args = argparse.Namespace(
                unet_config_path=config_path,
                inference_ckpt_path=ckpt_path,
                video_path=video_path,
                audio_path=audio_path,
                video_out_path=output_video_path,
                seed=seed,
                inference_steps=inference_steps,
                guidance_scale=lips_expression,  # Using lips_expression for the guidance_scale
                scheduler_config_path=scheduler_config_path,
                whisper_ckpt_path=whisper_ckpt_path,
                device=device,
                batch_size=BATCH_SIZE,
                use_mixed_precision=use_mixed_precision,
                temp_dir=temp_dir,
                mask_image_path=mask_image_path
            )

            # Set PYTHONPATH to include our directories 
            package_root = os.path.dirname(cur_dir)
            if package_root not in sys.path:
                sys.path.insert(0, package_root)
            if cur_dir not in sys.path:
                sys.path.insert(0, cur_dir)

            # Clean GPU cache before inference
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                
            # Check and prevent ComfyUI temp creation again
            comfyui_temp = get_comfyui_temp_dir()
            if comfyui_temp and os.path.exists(comfyui_temp):
                try:
                    os.rename(comfyui_temp, f"{comfyui_temp}_backup_{uuid.uuid4().hex[:8]}")
                except:
                    pass

            # Import the inference module
            inference_module = import_inference_script(inference_script_path)
            
            # Monkey patch any temp directory functions in the inference module
            if hasattr(inference_module, 'get_temp_dir'):
                inference_module.get_temp_dir = lambda *args, **kwargs: temp_dir
                
            # Create subdirectories that the inference module might expect
            inference_temp = os.path.join(temp_dir, "temp")
            os.makedirs(inference_temp, exist_ok=True)
            
            # Run inference
            inference_module.main(config, args)

            # Clean GPU cache after inference
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            # Verify output file exists
            if not os.path.exists(output_video_path):
                raise FileNotFoundError(f"Output video not found at: {output_video_path}")
            
            # Create a permanent output location
            output_dir = os.path.join(get_ext_dir(), "outputs")
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate a unique filename for the permanent output
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            permanent_output_path = os.path.join(output_dir, f"latentsync_output_{timestamp}.mp4")
            
            # Copy the output file to the permanent location
            shutil.copy2(output_video_path, permanent_output_path)
            
            return (permanent_output_path,)

        except Exception as e:
            print(f"Error during inference: {str(e)}")
            import traceback
            traceback.print_exc()
            raise

        finally:
            # Clean up temporary files
            if output_video_path and os.path.exists(output_video_path):
                try:
                    os.remove(output_video_path)
                    print(f"Removed temporary file: {output_video_path}")
                except Exception as e:
                    print(f"Failed to remove {output_video_path}: {str(e)}")

            # Remove temporary run directory
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    print(f"Removed run temporary directory: {temp_dir}")
                except Exception as e:
                    print(f"Failed to remove temp run directory: {str(e)}")

            # Clean up any ComfyUI temp directories again (in case they were created during execution)
            cleanup_comfyui_temp_directories()

            # Final GPU cache cleanup
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

class VideoBasicLatentSyncLengthAdjuster:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video_path": ("STRING", {"default": ""}),
                "audio_path": ("STRING", {"default": ""}),
                "mode": (["normal", "pingpong", "loop_to_audio"], {"default": "normal"}),
                "fps": ("FLOAT", {"default": 25.0, "min": 1.0, "max": 120.0}),
                "silent_padding_sec": ("FLOAT", {"default": 0.5, "min": 0.1, "max": 3.0, "step": 0.1}),
            }
        }

    CATEGORY = "LatentSyncNode"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_path",)
    FUNCTION = "adjust"

    def adjust(self, video_path, audio_path, mode, fps=25.0, silent_padding_sec=0.5):
        # Validate input paths
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Input video file not found: {video_path}")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Input audio file not found: {audio_path}")
        
        # Use our module temp directory
        global MODULE_TEMP_DIR
        
        # Create a run-specific subdirectory in our temp directory
        run_id = ''.join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(5))
        temp_dir = os.path.join(MODULE_TEMP_DIR, f"vla_run_{run_id}")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Create output video path in our system temp directory
        output_video_path = os.path.join(temp_dir, f"adjusted_{run_id}.mp4")
        
        try:
            # Load audio file
            waveform, sample_rate = torchaudio.load(audio_path)
            
            # Extract frames from video using ffmpeg
            import ffmpeg
            
            # Get video info
            probe = ffmpeg.probe(video_path)
            video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            original_fps = float(eval(video_info.get('r_frame_rate', str(fps))))
            width = int(video_info['width'])
            height = int(video_info['height'])
            
            # Create temp directory for frames
            frames_dir = os.path.join(temp_dir, "frames")
            os.makedirs(frames_dir, exist_ok=True)
            
            # Extract frames
            (
                ffmpeg
                .input(video_path)
                .output(os.path.join(frames_dir, "frame%04d.png"), r=original_fps)
                .run(quiet=True, overwrite_output=True)
            )
            
            # Get list of frames
            frame_files = sorted([f for f in os.listdir(frames_dir) if f.startswith("frame") and f.endswith(".png")])
            
            # Process based on mode
            if mode == "normal":
                # Add silent padding to the audio
                audio_duration = waveform.shape[1] / sample_rate
                silence_samples = math.ceil(silent_padding_sec * sample_rate)
                silence = torch.zeros((waveform.shape[0], silence_samples), dtype=waveform.dtype)
                padded_audio = torch.cat([waveform, silence], dim=1)
                
                # Calculate required frames based on the padded audio
                padded_audio_duration = (waveform.shape[1] + silence_samples) / sample_rate
                required_frames = int(padded_audio_duration * fps)
                
                if len(frame_files) > required_frames:
                    # Trim video frames to match padded audio duration
                    adjusted_frames = frame_files[:required_frames]
                else:
                    # If video is shorter than padded audio, keep all video frames
                    # and trim the audio accordingly
                    adjusted_frames = frame_files
                    required_samples = int(len(frame_files) / fps * sample_rate)
                    padded_audio = padded_audio[:, :required_samples]
                
                # Save adjusted audio
                temp_audio_path = os.path.join(temp_dir, "adjusted_audio.wav")
                torchaudio.save(temp_audio_path, padded_audio.unsqueeze(0), sample_rate)
                
                # Create output directory for adjusted frames
                adjusted_frames_dir = os.path.join(temp_dir, "adjusted_frames")
                os.makedirs(adjusted_frames_dir, exist_ok=True)
                
                # Copy selected frames to adjusted directory
                for i, frame in enumerate(adjusted_frames):
                    shutil.copy2(
                        os.path.join(frames_dir, frame),
                        os.path.join(adjusted_frames_dir, f"adjusted_frame{i:04d}.png")
                    )
                
            elif mode == "pingpong":
                video_duration = len(frame_files) / original_fps
                audio_duration = waveform.shape[1] / sample_rate
                
                if audio_duration <= video_duration:
                    # Audio is shorter than video, pad with silence
                    required_samples = int(video_duration * sample_rate)
                    silence = torch.zeros((waveform.shape[0], required_samples - waveform.shape[1]), dtype=waveform.dtype)
                    adjusted_audio = torch.cat([waveform, silence], dim=1)
                    
                    # Save adjusted audio
                    temp_audio_path = os.path.join(temp_dir, "adjusted_audio.wav")
                    torchaudio.save(temp_audio_path, adjusted_audio.unsqueeze(0), sample_rate)
                    
                    # Use all original frames
                    adjusted_frames_dir = frames_dir
                    
                else:
                    # Audio is longer than video, create pingpong effect
                    silence_samples = math.ceil(silent_padding_sec * sample_rate)
                    silence = torch.zeros((waveform.shape[0], silence_samples), dtype=waveform.dtype)
                    padded_audio = torch.cat([waveform, silence], dim=1)
                    total_duration = (waveform.shape[1] + silence_samples) / sample_rate
                    target_frames = math.ceil(total_duration * fps)
                    
                    # Create pingpong frame sequence
                    reversed_frames = frame_files[::-1][1:-1]  # Remove endpoints
                    pingpong_frames = frame_files + reversed_frames
                    
                    # Loop if needed
                    while len(pingpong_frames) < target_frames:
                        pingpong_frames += pingpong_frames[:target_frames - len(pingpong_frames)]
                    
                    # Save adjusted audio
                    temp_audio_path = os.path.join(temp_dir, "adjusted_audio.wav")
                    torchaudio.save(temp_audio_path, padded_audio.unsqueeze(0), sample_rate)
                    
                    # Create output directory for adjusted frames
                    adjusted_frames_dir = os.path.join(temp_dir, "adjusted_frames")
                    os.makedirs(adjusted_frames_dir, exist_ok=True)
                    
                    # Copy selected frames to adjusted directory
                    for i, frame in enumerate(pingpong_frames[:target_frames]):
                        source_frame = os.path.join(frames_dir, frame_files[int(frame_files.index(frame) if frame in frame_files else 0)])
                        shutil.copy2(
                            source_frame,
                            os.path.join(adjusted_frames_dir, f"adjusted_frame{i:04d}.png")
                        )
                
            elif mode == "loop_to_audio":
                # Add silent padding then simple loop
                silence_samples = math.ceil(silent_padding_sec * sample_rate)
                silence = torch.zeros((waveform.shape[0], silence_samples), dtype=waveform.dtype)
                padded_audio = torch.cat([waveform, silence], dim=1)
                total_duration = (waveform.shape[1] + silence_samples) / sample_rate
                target_frames = math.ceil(total_duration * fps)
                
                # Create looped frame sequence
                looped_frames = []
                while len(looped_frames) < target_frames:
                    looped_frames += frame_files[:target_frames - len(looped_frames)]
                
                # Save adjusted audio
                temp_audio_path = os.path.join(temp_dir, "adjusted_audio.wav")
                torchaudio.save(temp_audio_path, padded_audio.unsqueeze(0), sample_rate)
                
                # Create output directory for adjusted frames
                adjusted_frames_dir = os.path.join(temp_dir, "adjusted_frames")
                os.makedirs(adjusted_frames_dir, exist_ok=True)
                
                # Copy selected frames to adjusted directory
                for i, frame in enumerate(looped_frames[:target_frames]):
                    source_frame = os.path.join(frames_dir, frame)
                    shutil.copy2(
                        source_frame,
                        os.path.join(adjusted_frames_dir, f"adjusted_frame{i:04d}.png")
                    )
            
            # Combine frames and audio into output video
            (
                ffmpeg
                .input(os.path.join(adjusted_frames_dir, "adjusted_frame%04d.png"), r=fps)
                .input(temp_audio_path)
                .output(output_video_path, vcodec='libx264', pix_fmt='yuv420p', acodec='aac', strict='experimental')
                .run(quiet=True, overwrite_output=True)
            )
            
            # Create a permanent output location
            output_dir = os.path.join(get_ext_dir(), "outputs")
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate a unique filename for the permanent output
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            permanent_output_path = os.path.join(output_dir, f"adjusted_video_{timestamp}.mp4")
            
            # Copy the output file to the permanent location
            shutil.copy2(output_video_path, permanent_output_path)
            
            return (permanent_output_path,)
            
        except Exception as e:
            print(f"Error during video length adjustment: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
            
        finally:
            # Clean up temporary files
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    print(f"Removed temporary directory: {temp_dir}")
                except Exception as e:
                    print(f"Failed to remove temp directory: {str(e)}")

# Node Mappings for ComfyUI
NODE_CLASS_MAPPINGS = {
    "VideoBasicLatentSyncNode": VideoBasicLatentSyncNode,
    "VideoBasicLatentSyncLengthAdjuster": VideoBasicLatentSyncLengthAdjuster,
}

# Display Names for ComfyUI
NODE_DISPLAY_NAME_MAPPINGS = {
    "VideoBasicLatentSyncNode": "VideoBasic LatentSync Node",
    "VideoBasicLatentSyncLengthAdjuster": "VideoBasic LatentSync Length Adjuster",
 }