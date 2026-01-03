import struct
import os
import json

def write_u8(f, val):
    f.write(struct.pack('<B', val))

def write_u16le(f, val):
    f.write(struct.pack('<H', val))

def write_u32le(f, val):
    f.write(struct.pack('<I', val))

def write_u32be(f, val):
    f.write(struct.pack('>I', val))

def write_id32be(f, val):
    if isinstance(val, str):
        val = val.encode('ascii')
    f.write(val[:4])

def read_wav_data(filename):
    with open(filename, 'rb') as f:
        # Simple WAV parser to find 'data' chunk
        try:
            riff = f.read(4)
            if riff != b'RIFF':
                raise ValueError("Not a RIFF file")
            f.seek(4, 1) # size
            wave = f.read(4)
            if wave != b'WAVE':
                raise ValueError("Not a WAVE file")
            
            while True:
                chunk_id = f.read(4)
                if len(chunk_id) < 4:
                    break
                chunk_size = struct.unpack('<I', f.read(4))[0]
                
                if chunk_id == b'data':
                    return f.read(chunk_size)
                
                f.seek(chunk_size, 1)
        except Exception as e:
            print(f"Error reading {filename}: {e}")
            return b''
    return b''

def align_file(f, alignment):
    pos = f.tell()
    rem = pos % alignment
    if rem != 0:
        pad = alignment - rem
        f.write(b'\x00' * pad)

import hashlib

def build_kwb_header_and_body(chunk_layout):
    # This function constructs the KWB Header blob and the KWB Body blob
    # It returns (header_bytes, body_bytes)
    
    body_data = bytearray()
    
    # Header construction
    
    sound_entries = chunk_layout["sound_entries"]
    num_sounds = len(sound_entries)
    
    # Temporary buffer for Sound Entry Headers
    sound_entry_buffers = []
    sound_entry_offsets = [] # Relative to KWB Header start
    
    # Start of Sound Entries Data area (after header + offset table)
    current_entry_offset = 0x18 + num_sounds * 4
    
    # Deduplication map
    # Hash -> (offset, size)
    data_map = {}
    
    for entry in sound_entries:
        subsounds = entry["subsounds"]
        version = entry.get("version", 32768) # Default 0x8000
        
        entry_buffer = bytearray()
        
        # Sound Entry Header
        entry_buffer.extend(struct.pack('<H', version))
        entry_buffer.extend(b'\x00') # 0x02
        entry_buffer.extend(struct.pack('<B', len(subsounds)))
        
        entry_buffer.extend(b'\x00' * (0x2C - 0x04))
        
        # Subsound entries
        for sub in subsounds:
            sub_start_offset = len(entry_buffer)
            
            # Load WAV data
            wav_path = sub["filename"] # logical path from layout
            if not os.path.exists(wav_path):
                print(f"Warning: {wav_path} not found.")
                raw_data = b''
            else:
                raw_data = read_wav_data(wav_path)
            
            # Calculate hash for deduplication
            data_hash = hashlib.sha256(raw_data).digest()
            
            if data_hash in data_map:
                # Reuse existing data
                current_stream_offset, current_stream_size = data_map[data_hash]
            else:
                # Append new data
                current_stream_offset = len(body_data)
                current_stream_size = len(raw_data)
                
                body_data.extend(raw_data)
                data_map[data_hash] = (current_stream_offset, current_stream_size)
            
            # Fill Entry
            entry_buffer.extend(struct.pack('<H', sub["sample_rate"]))
            entry_buffer.extend(struct.pack('<B', sub["codec"]))
            entry_buffer.extend(struct.pack('<B', sub["channels"]))
            entry_buffer.extend(struct.pack('<H', sub["block_size"]))
            
            entry_buffer.extend(b'\x00' * (0x10 - 0x06)) # Padding 0x06-0x0F
            
            entry_buffer.extend(struct.pack('<I', current_stream_offset))
            entry_buffer.extend(struct.pack('<I', current_stream_size))
            
            # Padding to 0x48 bytes
            written_so_far = len(entry_buffer) - sub_start_offset
            remaining = 0x48 - written_so_far
            entry_buffer.extend(b'\x00' * remaining)
            
        sound_entry_buffers.append(entry_buffer)
        sound_entry_offsets.append(current_entry_offset)
        current_entry_offset += len(entry_buffer)
        
    # Construct Final Header
    header_blob = bytearray()
    
    # 0x00: KWB2
    header_blob.extend(b'\x4B\x57\x42\x32')
    # 0x04: 0
    header_blob.extend(struct.pack('<I', 0))
    header_blob[4:8] = b'\x00\x00\x00\x00'
    
    # Write sounds count at 0x06
    struct.pack_into('<H', header_blob, 0x06, num_sounds)
    
    # 0x08-0x17: Padding
    header_blob.extend(b'\x00' * 16)
    
    # 0x18: Offset Table
    for offset in sound_entry_offsets:
        header_blob.extend(struct.pack('<I', offset))
        
    # Append Entry Buffers
    for buf in sound_entry_buffers:
        header_blob.extend(buf)
        
    return header_blob, body_data


def repack(layout_path, output_path):
    with open(layout_path, 'r') as f:
        layout = json.load(f)
        
    chunks = layout["chunks"]
    
    with open(output_path, 'wb') as f:
        # XWS Header
        # 0x00 Magic "XWSF"
        f.write(b'XWSF')
        # 0x04 Version? 0x01010000 (BE)?
        # kwb.c: "0a: version? (0100: NG2... 0101: DoA LR PC)"
        # XWSF is 4 bytes. 0x04-0x07 is 0?
        # kwb.c: `kwb->big_endian = read_u8(offset + 0x08, sf) == 0xFF;`
        # 0x08-0x0B
        # Let's try to infer from typical.
        # Let's write 0 for 0x04-0x07.
        f.write(b'\x00\x00\x00\x00')
        
        # 0x08: Endianness (0xFF = BE, else LE)
        # Windows/PC is usually LE. So 0x00.
        f.write(b'\x00')
        # 0x09: ?
        f.write(b'\x00')
        # 0x0A: Version (0x0101 for DOA LR PC)
        # LE: 0x01 0x01
        f.write(b'\x01\x01')
        
        # 0x0C: Tables start (usually 0x20)
        # 0x10: File size (placeholder)
        # 0x14: chunks2 (count)
        # 0x18: chunks (count)
        # 0x1C: null
        
        # We have N KWB chunks. Each uses 2 XWS slots.
        num_kwb_chunks = len(chunks)
        total_chunks = num_kwb_chunks * 2
        
        # Placeholder for offsets
        f.write(struct.pack('<I', 0x20)) # Tables start
        f.write(struct.pack('<I', 0)) # File size placeholder
        f.write(struct.pack('<I', total_chunks)) # chunks2
        f.write(struct.pack('<I', total_chunks)) # chunks
        f.write(struct.pack('<I', 0)) # Padding
        
        # 0x20: Table 1 Offset (pointers)
        # 0x24: Table 2 Offset (sizes) - optional?
        # extract_kwb_multi says read 0x20. Doesn't mention 0x24.
        # kwb.c: "DoA LR PC doesn't (not very useful)" regarding table 2.
        # So we can put 0 for table 2 offset.
        f.write(struct.pack('<I', 0x28)) # Table 1 offset (relative to file start? No, relative to 0x00? "offset + table1_offset")
        # In parse_xws: table1_offset = read_u32le(f, 0x20).
        # head_offset = read_u32le(f, table1_offset + i*4).
        # If table1 starts immediately after header (which is 0x28 bytes so far: 0x20 + 8 bytes of offsets?)
        # Header is 0x20 bytes + 0x08 bytes of table pointers = 0x28 bytes.
        
        # Wait, 0x20 contains the *offset value*.
        # 0x20: 0x28 (points to 0x28)
        # 0x24: 0
        f.write(struct.pack('<I', 0))
        
        # 0x28: Start of Table 1 (Offsets)
        # Size = total_chunks * 4
        table1_start = f.tell()
        for _ in range(total_chunks):
            f.write(struct.pack('<I', 0)) # Placeholders
            
        # End of Header area.
        # Align to 0x800? extraction script showed first chunk at 0x800.
        align_file(f, 0x800)
        
        table1_offsets = []
        
        for k_idx, chunk in enumerate(chunks):
            # Build Metadata and Body
            header_blob, body_blob = build_kwb_header_and_body(chunk)
            
            # Write Header Chunk
            current_pos = f.tell()
            table1_offsets.append(current_pos)
            f.write(header_blob)
            
            # Align before Body?
            align_file(f, 0x800)
            
            # Write Body Chunk
            current_pos = f.tell()
            table1_offsets.append(current_pos)
            f.write(body_blob)
            
            # Align after Body for next chunk?
            if k_idx < len(chunks) - 1:
                align_file(f, 0x800)
                
        # Final file size alignment?
        align_file(f, 0x800)
        
        # Update File Size
        file_size = f.tell()
        f.seek(0x10)
        f.write(struct.pack('<I', file_size))
        
        # Update Table 1
        f.seek(table1_start)
        for off in table1_offsets:
            f.write(struct.pack('<I', off))
            
    print(f"Repacked to {output_path}")

if __name__ == "__main__":
    if os.path.exists("layout.json"):
        repack("layout.json", "SOUND_035_EN_REPACK.xws")
    else:
        print("layout.json not found.")
