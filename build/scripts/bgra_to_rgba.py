def swap_bytes_and_overwrite(file_path):
    # Read the file in binary mode
    with open(file_path, 'rb') as file:
        data = file.read()

    # Modify the data by swapping the first and third bytes of each four-byte chunk
    modified_data = bytearray(data)
    for i in range(0, len(modified_data), 4):
        if i + 2 < len(modified_data):  # Ensure there's a third byte to swap with
            modified_data[i], modified_data[i+2] = modified_data[i+2], modified_data[i]

    # Overwrite the file with the modified data
    with open(file_path, 'wb') as file:
        file.write(modified_data)

# Usage
file_path = '/home/smith/Agon/mystuff/pingo/assets/viking.rgba'
swap_bytes_and_overwrite(file_path)
