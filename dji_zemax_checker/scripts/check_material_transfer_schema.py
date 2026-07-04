#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Lightweight schema checker to verify that the headers in the processed CSV files
exactly match the definitions in docs/material_transfer_schema.md.
"""

import sys
from pathlib import Path

# Expected schemas from methodology definitions
EXPECTED_SCHEMAS = {
    "data/processed/donor_native_table.csv": [
        "donor_id", "source", "topology_type", "lens_count", "surface_count",
        "EFL_native", "F_number_native", "HFOV_native", "TTL_native", "BFL_native",
        "image_height_native", "material_completeness", "native_replay_status",
        "native_trace_status", "notes"
    ],
    "data/processed/material_vector_table.csv": [
        "material_id", "material_name", "source_library", "nd", "Vd", "PgF",
        "material_type", "available_in_dji", "notes"
    ],
    "data/processed/donor_material_sequence.csv": [
        "donor_id", "lens_id", "native_material", "native_nd", "native_Vd",
        "lens_power_sign", "lens_role", "position_role", "dji_best_match",
        "dji_nd", "dji_Vd", "nd_error", "Vd_error", "role_match_status",
        "mapping_score"
    ],
    "data/processed/material_transfer_result.csv": [
        "donor_id", "transfer_version", "mapping_method", "material_coverage_score",
        "EFL_before", "EFL_after", "BFL_before", "BFL_after", "TTL_before", "TTL_after",
        "max_pass_field_before", "max_pass_field_after", "failure_surface_before",
        "failure_surface_after", "transfer_status", "notes"
    ],
    "data/processed/donor_transfer_label.csv": [
        "donor_id", "native_status", "model_glass_status", "dji_transfer_status",
        "dominant_failure_reason", "usable_for_structure_dataset",
        "usable_for_material_dataset", "usable_for_ml_training", "notes"
    ]
}

def check_schema():
    # Root of the dji_zemax_checker project directory
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent
    
    mismatches = 0
    
    print("Starting Material Transfer CSV Schema Validation...")
    print(f"Project Root: {project_root}\n")
    
    for rel_path, expected_fields in EXPECTED_SCHEMAS.items():
        file_path = project_root / rel_path
        print(f"Checking: {rel_path} -> ", end="")
        
        if not file_path.exists():
            print("FAILED (File does not exist)")
            mismatches += 1
            continue
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                header_line = f.readline().strip()
                
            if not header_line:
                print("FAILED (Empty file or missing header)")
                mismatches += 1
                continue
                
            actual_fields = [field.strip() for field in header_line.split(",") if field.strip()]
            
            # Compare lists exactly (order and elements)
            if actual_fields == expected_fields:
                print("PASS")
            else:
                print("FAILED")
                mismatches += 1
                print(f"  Expected: {expected_fields}")
                print(f"  Actual:   {actual_fields}")
                
                # Check for differences
                expected_set = set(expected_fields)
                actual_set = set(actual_fields)
                
                missing = expected_set - actual_set
                extra = actual_set - expected_set
                
                if missing:
                    print(f"  Missing fields: {list(missing)}")
                if extra:
                    print(f"  Extra fields:   {list(extra)}")
                if not missing and not extra and actual_fields != expected_fields:
                    print("  Mismatch details: Order of fields is incorrect.")
                    
        except Exception as e:
            print(f"FAILED (Error reading file: {e})")
            mismatches += 1
            
    print("\n-------------------------------------------")
    if mismatches == 0:
        print("All schemas match perfectly. PASS.")
        return 0
    else:
        print(f"Schema check failed with {mismatches} errors. FAIL.")
        return 1

if __name__ == "__main__":
    sys.exit(check_schema())
