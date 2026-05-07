import os
import logging
from typing import List, Dict, Tuple
import gpxpy
import numpy as np
from crewai.tools import tool


logger = logging.getLogger(__name__)

def parse_gpx(file_path: str) -> np.ndarray:
    """
    Parses a GPX file and extracts latitude and longitude coordinates.
    Returns a numpy array of shape (N, 2) where each row is (lat, lon).
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        gpx = gpxpy.parse(f)
        
    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points.append((point.latitude, point.longitude))
                
    return np.array(points)

def calculate_similarity(coords_a: np.ndarray, coords_b: np.ndarray, threshold_meters: float = 50.0) -> float:
    """
    Calculates the spatial overlap similarity between two sets of coordinates.
    Returns a score between 0.0 and 1.0.
    
    A point in Route A is considered "overlapping" if there is at least one point
    in Route B within `threshold_meters`.
    """
    if len(coords_a) == 0 or len(coords_b) == 0:
        return 0.0
        
    # Convert lat/lon to radians
    coords_a_rad = np.radians(coords_a)
    coords_b_rad = np.radians(coords_b)
    
    # Earth radius in meters
    R = 6371000.0
    
    # Process in chunks to avoid large memory allocations
    # (e.g., 5000 x 5000 floats = 200MB, which is fine, but chunking is safer)
    chunk_size = 1000
    overlap_a = 0
    overlap_b = 0
    
    # 1. For each point in A, find if there is a point in B within threshold
    for i in range(0, len(coords_a_rad), chunk_size):
        chunk_a = coords_a_rad[i:i+chunk_size]
        
        lat1 = chunk_a[:, 0, np.newaxis]
        lon1 = chunk_a[:, 1, np.newaxis]
        lat2 = coords_b_rad[:, 0]
        lon2 = coords_b_rad[:, 1]
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = np.sin(dlat / 2.0)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0)**2
        c = 2 * np.arcsin(np.clip(np.sqrt(a), 0.0, 1.0))
        distances = R * c
        
        min_dists = np.min(distances, axis=1)
        overlap_a += np.sum(min_dists <= threshold_meters)
        
    # 2. For each point in B, find if there is a point in A within threshold
    for i in range(0, len(coords_b_rad), chunk_size):
        chunk_b = coords_b_rad[i:i+chunk_size]
        
        lat1 = chunk_b[:, 0, np.newaxis]
        lon1 = chunk_b[:, 1, np.newaxis]
        lat2 = coords_a_rad[:, 0]
        lon2 = coords_a_rad[:, 1]
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = np.sin(dlat / 2.0)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0)**2
        c = 2 * np.arcsin(np.clip(np.sqrt(a), 0.0, 1.0))
        distances = R * c
        
        min_dists = np.min(distances, axis=1)
        overlap_b += np.sum(min_dists <= threshold_meters)
        
    score_a = overlap_a / len(coords_a)
    score_b = overlap_b / len(coords_b)
    
    # Return average overlap percentage
    return (score_a + score_b) / 2.0

def analyze_gpx_similarity(gpx_files: List[str], threshold_meters: float = 50.0) -> Dict[Tuple[str, str], float]:
    """
    Analyzes a list of GPX files and returns pairwise similarity scores.
    Returns a dictionary with keys as (file1, file2) and values as the similarity score.
    """
    parsed_routes = {}
    for file_path in gpx_files:
        try:
            parsed_routes[file_path] = parse_gpx(file_path)
        except Exception as e:
            logger.error(f"Error parsing {file_path}: {e}")
            
    files = list(parsed_routes.keys())
    similarity_matrix = {}
    
    for i in range(len(files)):
        for j in range(i + 1, len(files)):
            file_a = files[i]
            file_b = files[j]
            score = calculate_similarity(parsed_routes[file_a], parsed_routes[file_b], threshold_meters)
            
            similarity_matrix[(os.path.basename(file_a), os.path.basename(file_b))] = score
            
    return similarity_matrix

@tool("Analyze GPX Similarity")
def execute_gpx_similarity_analysis(files: List[str]) -> str:
    """
    Analyzes the spatial similarity of a provided list of GPX file paths.
    Accepts a list of absolute file paths to GPX files as input.
    Returns a formatted string detailing the pairwise overlap percentage between each pair of files.
    This is extremely useful for determining if two or more cycling routes are physically similar or overlapping.
    """    
    if not files:
        return "No GPX files provided for analysis."
    
    # Take up to 5 files to quickly test the function
    files_to_test = files[:5]
    result_str = f"Analyzing similarity for {len(files_to_test)} GPX files...\n"
    
    results = analyze_gpx_similarity(files_to_test, threshold_meters=50.0)
    
    result_str += "\nSimilarity Scores (0.0 to 1.0):\n"
    for (f1, f2), score in sorted(results.items(), key=lambda x: x[1], reverse=True):
        result_str += f"{f1} <-> {f2}: {score:.2%} overlap\n"
        
    return result_str
