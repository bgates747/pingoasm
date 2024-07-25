#!/bin/bash

# Check if an argument (filename) is provided
if [ "$#" -ne 1 ]; then
    echo "Usage: $0 filename.obj"
    exit 1
fi

# Assign the input filename to a variable
file="$1"

# Check if the file exists
if [ ! -f "$file" ]; then
    echo "File not found!"
    exit 1
fi

# Initialize counters
vertex_count=0
face_count=0
uv_count=0
index_count=0

# Read the file line by line
while IFS= read -r line; do
    case "$line" in
        v\ *)      # Vertex
            vertex_count=$((vertex_count + 1))
            ;;
        vt\ *)     # Texture coordinate (UV)
            uv_count=$((uv_count + 1))
            ;;
        f\ *)      # Face
            face_count=$((face_count + 1))
            # Count the number of UV indices in the face definition
            uv_indices=$(echo "$line" | grep -o '\/[0-9]*\/' | wc -l)
            index_count=$((index_count + uv_indices))
            ;;
    esac
done < "$file"

# Output the results
echo "Number of vertices: $vertex_count"
echo "Number of faces: $face_count"
echo "Number of UVs: $uv_count"
echo "Number of indices: $index_count"
