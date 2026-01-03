import struct
import os
import json

def read_u8(f, offset):
    f.seek(offset)
    return struct.unpack('<B', f.read(1))[0]

def read_u16le(f, offset):
    f.seek(offset)
    return struct.unpack('<H', f.read(2))[0]

def read_u32le(f, offset):
    f.seek(offset)
    return struct.unpack('<I', f.read(4))[0]

def read_u32be(f, offset):
    f.seek(offset)
    return struct.unpack('>I', f.read(4))[0]

def read_id32be(f, offset):
    f.seek(offset)
    return f.read(4)

def write_wav_msadpcm(filename, data, channels, sample_rate, block_align):
    # Standard Microsoft ADPCM Coefficients
    coeffs = [
        (256, 0), (512, -256), (0, 0), (192, 64), 
        (240, 0), (460, -208), (392, -232)
    ]
    
    # Calculate samples per block
    # Formula: (BlockAlign - 7 * Channels) * 2 / Channels + 2
    samples_per_block = ((block_align - (7 * channels)) * 2) // channels + 2
    
    # WAV Header construction
    # RIFF chunk
    riff_fmt = b'RIFF'
    wave_fmt = b'WAVE'
    
    # fmt chunk
    fmt_id = b'fmt '
    # Size: 16 (base) + 2 (extra size) + 32 (extra data)
    # Actually for MSADPCM: 32 bytes standard + 2 byte wNumCoef + coeffs * 4
    # 32 + 2 + 7*4 = 62 bytes total extra data? 
    # Standard fmt chunk size = 18 + cbSize
    # cbSize = 32
    # wSamplesPerBlock (2) + wNumCoef (2) + 7*4 (28) = 32 bytes
    
    fmt_chunk_size = 50 # 18 (base fmt) + 32 (extra)
    audio_format = 2 # MS ADPCM
    byte_rate = (sample_rate * block_align) // samples_per_block
    bits_per_sample = 4
    cb_size = 32 # Extra size
    
    w_samples_per_block = samples_per_block
    w_num_coef = len(coeffs)
    
    with open(filename, 'wb') as f:
        # RIFF Header
        f.write(riff_fmt)
        f.write(struct.pack('<I', 0)) # Placeholder for file size
        f.write(wave_fmt)
        
        # fmt chunk
        f.write(fmt_id)
        f.write(struct.pack('<I', fmt_chunk_size))
        f.write(struct.pack('<H', audio_format))
        f.write(struct.pack('<H', channels))
        f.write(struct.pack('<I', sample_rate))
        f.write(struct.pack('<I', byte_rate))
        f.write(struct.pack('<H', block_align))
        f.write(struct.pack('<H', bits_per_sample))
        f.write(struct.pack('<H', cb_size))
        
        # MSADPCM specific
        f.write(struct.pack('<H', w_samples_per_block))
        f.write(struct.pack('<H', w_num_coef))
        for c1, c2 in coeffs:
            f.write(struct.pack('<hh', c1, c2))
            
        # data chunk
        f.write(b'data')
        f.write(struct.pack('<I', len(data)))
        f.write(data)
        
        # Update RIFF size
        file_size = f.tell()
        f.seek(4)
        f.write(struct.pack('<I', file_size - 8))

def parse_xws(file_path):
    print(f"Opening {file_path}...")
    layout = {
        "original_file": os.path.basename(file_path),
        "chunks": []
    }

    with open(file_path, 'rb') as f:
        # Check XWS Header
        magic = read_id32be(f, 0)
        if magic not in [b'XWSF', b'tdpa']:
            print("Invalid XWS header.")
            return

        # Basic XWS parsing logic
        chunks = read_u32le(f, 0x18)
        table1_offset = read_u32le(f, 0x20) # Offsets
        
        print(f"Found {chunks} chunks in XWS header.")

        kwb_index = 0
        i = 0
        while i < chunks:
            # Read entry offset from table 1
            head_offset = read_u32le(f, table1_offset + i * 4)
            if head_offset == 0:
                i += 1
                continue
            
            # Check entry type
            entry_type = read_u32be(f, head_offset)
            
            # Check for KWB2 (0x4B574232)
            if entry_type == 0x4B574232: 
                kwb_index += 1
                folder_name = os.path.join("test_extracted_kwb", f"kwb_{kwb_index}")
                
                if not os.path.exists(folder_name):
                    os.makedirs(folder_name)
                    
                print(f"Found KWB chunk #{kwb_index} at 0x{head_offset:X}. Extracting to {folder_name}...")
                
                # Body offset is usually the next entry for KWB2 in XWS
                # Logic from kwb.c: offset + table1_offset + i*0x04 + 0x04
                body_offset = read_u32le(f, table1_offset + (i + 1) * 4)
                
                # Parse and extract this KWB chunk
                chunk_data = parse_kwb2(f, head_offset, body_offset, folder_name)
                chunk_data["index"] = kwb_index
                layout["chunks"].append(chunk_data)
                
                # KWB2 takes 2 slots (head + body)
                i += 2
            else:
                # Skip other chunk types
                i += 1
    
    with open("layout.json", "w") as f:
        json.dump(layout, f, indent=4)
    print("Saved layout.json")

def parse_kwb2(f, head_offset, body_offset, folder_name):
    # 0x06: number of sounds
    sounds = read_u16le(f, head_offset + 0x06)
    print(f"  - Contains {sounds} sound entries.")
    
    chunk_info = {
        "type": "KWB2",
        "sound_entries": []
    }

    # Start naming at 1.wav
    track_count = 1
    
    # The offset table starts at 0x18 inside the KWB header
    for i in range(sounds):
        entry_offset_loc = head_offset + 0x18 + i * 4
        sound_rel_offset = read_u32le(f, entry_offset_loc)
        
        entry_info = {
            "entry_index": i,
            "offset_loc_rel": 0x18 + i * 4,
            "subsounds": []
        }

        if sound_rel_offset == 0:
            chunk_info["sound_entries"].append(entry_info)
            continue
            
        sound_abs_offset = head_offset + sound_rel_offset
        
        # Inside Sound Entry
        version = read_u16le(f, sound_abs_offset + 0x00)
        subsounds_count = read_u8(f, sound_abs_offset + 0x03)
        
        entry_info["version"] = version
        
        if version < 0xc000:
            subsound_start = 0x2c
            subsound_size = 0x48
        else:
            subsound_start = read_u16le(f, sound_abs_offset + 0x2c)
            subsound_size = read_u16le(f, sound_abs_offset + 0x2e)
            
        subsound_base = sound_abs_offset + subsound_start
        
        for j in range(subsounds_count):
            current_sub_offset = subsound_base + j * subsound_size
            
            codec = read_u8(f, current_sub_offset + 0x02)
            
            # Codec 0x10 is MSADPCM
            if codec == 0x10:
                sample_rate = read_u16le(f, current_sub_offset + 0x00)
                channels = read_u8(f, current_sub_offset + 0x03)
                block_size = read_u16le(f, current_sub_offset + 0x04)
                
                stream_rel_offset = read_u32le(f, current_sub_offset + 0x10)
                stream_size = read_u32le(f, current_sub_offset + 0x14)
                
                final_stream_offset = body_offset + stream_rel_offset
                
                # Extract Data
                f.seek(final_stream_offset)
                audio_data = f.read(stream_size)
                
                # Filename: 1.wav, 2.wav, etc.
                wav_filename = f"{track_count}.wav"
                output_filename = os.path.join(folder_name, wav_filename)
                
                write_wav_msadpcm(output_filename, audio_data, channels, sample_rate, block_size)
                
                subsound_info = {
                    "filename": output_filename.replace(os.sep, '/'),
                    "sample_rate": sample_rate,
                    "channels": channels,
                    "block_size": block_size,
                    "original_stream_size": stream_size,
                    "codec": codec
                }
                entry_info["subsounds"].append(subsound_info)
                
                track_count += 1
        
        chunk_info["sound_entries"].append(entry_info)
        
    return chunk_info

if __name__ == "__main__":
    file_name = "SOUND_035_EN_REPACK.xws"
    if os.path.exists(file_name):
        parse_xws(file_name)
    else:
        print(f"File {file_name} not found.")