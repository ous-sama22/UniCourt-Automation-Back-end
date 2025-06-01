# app/services/config_manager.py
import json
import os
import logging
from typing import Dict, Any, Tuple
from app.core.config import CONFIG_FILE_PATH, clear_cached_settings, get_app_settings, CLIENT_CONFIG_KEYS, UnicourtSelectors, AppSettings
from app.models_api.service import ConfigUpdateRequest # Ensure this import matches your file structure

logger = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self):
        self.config_file_path = CONFIG_FILE_PATH
        self._ensure_config_file_exists()

    def _ensure_config_file_exists(self):
        if not os.path.exists(self.config_file_path):
            logger.warning(f"{self.config_file_path} not found. Creating with current effective/default values.")
            try:
                # Get settings which already incorporate .env and code defaults
                # We only write client-configurable keys and selectors to config.json
                app_s = get_app_settings() 
                
                default_config: Dict[str, Any] = {
                    key: getattr(app_s, key) for key in CLIENT_CONFIG_KEYS
                }
                default_config["UNICOURT_SELECTORS"] = app_s.UNICOURT_SELECTORS.model_dump()
                # Add new client-configurable key for EXTRACT_ASSOCIATED_PARTY_ADDRESSES
                default_config["EXTRACT_ASSOCIATED_PARTY_ADDRESSES"] = app_s.EXTRACT_ASSOCIATED_PARTY_ADDRESSES


                with open(self.config_file_path, 'w') as f:
                    json.dump(default_config, f, indent=4)
                logger.info(f"Created default {self.config_file_path}. Review and update credentials/settings if necessary.")
            except Exception as e:
                logger.error(f"Could not create default config file {self.config_file_path}: {e}")

    def get_current_client_config_dict(self) -> Dict[str, Any]:
        self._ensure_config_file_exists()
        current_on_disk_config = {}
        try:
            with open(self.config_file_path, 'r') as f:
                current_on_disk_config = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read or parse {self.config_file_path}: {e}. Returning empty.")
            return {} 
        
        # Return only defined client keys, selectors, and new config items
        client_display_config = {
            key: current_on_disk_config.get(key) # Use .get for graceful missing keys
            for key in CLIENT_CONFIG_KEYS 
        }
        if "UNICOURT_SELECTORS" in current_on_disk_config:
            client_display_config["UNICOURT_SELECTORS"] = current_on_disk_config["UNICOURT_SELECTORS"]
        
        # Add EXTRACT_ASSOCIATED_PARTY_ADDRESSES if present in file, else default from AppSettings
        app_s_defaults = AppSettings() # To get default for new key if not in file
        client_display_config["EXTRACT_ASSOCIATED_PARTY_ADDRESSES"] = current_on_disk_config.get(
            "EXTRACT_ASSOCIATED_PARTY_ADDRESSES", app_s_defaults.EXTRACT_ASSOCIATED_PARTY_ADDRESSES
        )

        return client_display_config

    def update_client_config(self, update_data: ConfigUpdateRequest) -> Tuple[Dict[str, Any], bool]:
        self._ensure_config_file_exists()
        
        current_disk_config = {}
        try:
            with open(self.config_file_path, 'r') as f:
                current_disk_config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
             logger.warning(f"Error reading {self.config_file_path} during update ('{e}'); will create/overwrite.")
             current_disk_config = {} 
             # Initialize with default selectors and new config if creating fresh
             app_s_defaults = AppSettings()
             current_disk_config["UNICOURT_SELECTORS"] = app_s_defaults.UNICOURT_SELECTORS.model_dump()
             current_disk_config["EXTRACT_ASSOCIATED_PARTY_ADDRESSES"] = app_s_defaults.EXTRACT_ASSOCIATED_PARTY_ADDRESSES


        updated_fields_summary: Dict[str, Any] = {}
        # Use model_dump with exclude_none=True to only process fields explicitly set in the request
        update_dict = update_data.model_dump(exclude_none=True) 

        made_changes = False
        # Handle standard client credential keys
        for key, value in update_dict.items():
            if key in CLIENT_CONFIG_KEYS: # UNICOURT_EMAIL, UNICOURT_PASSWORD, OPENROUTER_API_KEY, OPENROUTER_LLM_MODEL
                if current_disk_config.get(key) != value: # value is not None here due to exclude_none
                    current_disk_config[key] = value 
                    updated_fields_summary[key] = value
                    made_changes = True
            elif key == "EXTRACT_ASSOCIATED_PARTY_ADDRESSES": # Handle new boolean config
                 if current_disk_config.get(key) != value: # value is not None here
                    current_disk_config[key] = value
                    updated_fields_summary[key] = value
                    made_changes = True


        if not made_changes:
            logger.info("No client-configurable settings were changed in the update request.")
            return {}, False # No restart needed if no changes

        try:
            with open(self.config_file_path, 'w') as f:
                json.dump(current_disk_config, f, indent=4) 
            logger.info(f"Client settings in {self.config_file_path} updated successfully: {updated_fields_summary}")
            
            clear_cached_settings() 
            # Any change to these client-configurable settings requires a restart to be effective
            return updated_fields_summary, True 
        except Exception as e:
            logger.error(f"Failed to write updated client settings to {self.config_file_path}: {e}")
            raise