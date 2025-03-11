import numpy as np

def chunk_transcript_by_time(transcript,
                             chunk_size=60):
    """
    Split a transcript into chunks based on time intervals.
    
    Args:
        transcript (dict): Dictionary containing transcript data with 'segments' key
        chunk_size (int): Size of each chunk in seconds (default: 60)
        
    Returns:
        list: List of text chunks
    """
    # Extract all segment end times
    ends = [segment['end'] for segment in transcript['segments']]
    
    if not ends:
        return []
    
    # Calculate chunk boundaries
    max_time = max(ends)
    num_chunks = int(np.ceil(max_time / chunk_size))
    chunk_times = [i * chunk_size for i in range(1, num_chunks + 1)]
    
    chunks = []
    current_chunk = ""
    current_chunk_idx = 0
    
    for i, segment in enumerate(transcript['segments']):
        # Add current segment to the chunk
        current_chunk += segment['text'] + ' '
        
        # Check if we've reached the end of a chunk or the last segment
        is_last_segment = i == len(transcript['segments']) - 1
        reached_chunk_boundary = (
            current_chunk_idx < len(chunk_times) and
            segment['end'] <= chunk_times[current_chunk_idx] and
            (is_last_segment or 
             i + 1 < len(transcript['segments']) and 
             transcript['segments'][i + 1]['end'] > chunk_times[current_chunk_idx])
        )
        
        if reached_chunk_boundary or is_last_segment:
            chunks.append(current_chunk.strip())
            current_chunk = ""
            current_chunk_idx += 1
    
    return chunks