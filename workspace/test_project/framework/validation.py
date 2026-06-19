"""Request validation and serialization"""
import re
from typing import Any, Dict, List, Optional, Type, get_type_hints
from dataclasses import dataclass, field, fields


class ValidationError(Exception):
    def __init__(self, errors: Dict[str, List[str]]):
        self.errors = errors
        super().__init__(str(errors))


class Schema:
    """Base schema for request validation"""
    
    @classmethod
    def validate(cls, data: dict) -> dict:
        errors = {}
        result = {}
        
        for f in fields(cls):
            value = data.get(f.name)
            rules = f.metadata.get("rules", {})
            
            # Required check
            if rules.get("required") and value is None:
                errors.setdefault(f.name, []).append(f"{f.name} is required")
                continue
            
            if value is None:
                result[f.name] = rules.get("default")
                continue
            
            # Type check
            expected_type = rules.get("type")
            if expected_type and not isinstance(value, expected_type):
                errors.setdefault(f.name, []).append(f"{f.name} must be {expected_type.__name__}")
                continue
            
            # String validations
            if isinstance(value, str):
                min_len = rules.get("min_length")
                max_len = rules.get("max_length")
                pattern = rules.get("pattern")
                
                if min_len and len(value) < min_len:
                    errors.setdefault(f.name, []).append(f"{f.name} must be at least {min_len} chars")
                if max_len and len(value) > max_len:
                    errors.setdefault(f.name, []).append(f"{f.name} must be at most {max_len} chars")
                if pattern and not re.match(pattern, value):
                    errors.setdefault(f.name, []).append(f"{f.name} format is invalid")
            
            # Numeric validations
            if isinstance(value, (int, float)):
                min_val = rules.get("min")
                max_val = rules.get("max")
                if min_val is not None and value < min_val:
                    errors.setdefault(f.name, []).append(f"{f.name} must be >= {min_val}")
                if max_val is not None and value > max_val:
                    errors.setdefault(f.name, []).append(f"{f.name} must be <= {max_val}")
            
            # List validations
            if isinstance(value, list):
                min_items = rules.get("min_items")
                max_items = rules.get("max_items")
                if min_items and len(value) < min_items:
                    errors.setdefault(f.name, []).append(f"{f.name} must have at least {min_items} items")
                if max_items and len(value) > max_items:
                    errors.setdefault(f.name, []).append(f"{f.name} must have at most {max_items} items")
            
            # Enum check
            enum_vals = rules.get("enum")
            if enum_vals and value not in enum_vals:
                errors.setdefault(f.name, []).append(f"{f.name} must be one of {enum_vals}")
            
            # Custom validator
            validator = rules.get("validator")
            if validator:
                try:
                    value = validator(value)
                except ValueError as e:
                    errors.setdefault(f.name, []).append(str(e))
                    continue
            
            result[f.name] = value
        
        # Cross-field validation
        cross_errors = cls._validate_cross(result)
        for field_name, msgs in cross_errors.items():
            errors.setdefault(field_name, []).extend(msgs)
        
        if errors:
            raise ValidationError(errors)
        
        return result

    @classmethod
    def _validate_cross(cls, data: dict) -> Dict[str, List[str]]:
        """Override for cross-field validation"""
        return {}


def validate_email(value: str) -> str:
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, value):
        raise ValueError("Invalid email format")
    return value


def validate_url(value: str) -> str:
    pattern = r'^https?://[^\s/$.?#].[^\s]*$'
    if not re.match(pattern, value):
        raise ValueError("Invalid URL format")
    return value


def validate_positive(value: (int, float)) -> (int, float):
    if value <= 0:
        raise ValueError("Must be positive")
    return value


# Common schema definitions
def field(required=False, default=None, type=None, min_length=None, max_length=None,
          min=None, max=None, pattern=None, enum=None, validator=None):
    """Helper to create field with validation rules"""
    rules = {}
    if required: rules["required"] = True
    if default is not None: rules["default"] = default
    if type: rules["type"] = type
    if min_length: rules["min_length"] = min_length
    if max_length: rules["max_length"] = max_length
    if min is not None: rules["min"] = min
    if max is not None: rules["max"] = max
    if pattern: rules["pattern"] = pattern
    if enum: rules["enum"] = enum
    if validator: rules["validator"] = validator
    return field_default(metadata={"rules": rules})


# Alias for dataclasses.field with metadata
from dataclasses import field as field_default
