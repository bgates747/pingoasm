import math

def parse_log(log_line):
    parts = log_line.split(', ')
    obj_id = int(parts[0].split(': ')[1])
    
    cam_pos = tuple(map(float, parts[1].split(': ')[1].strip('()').split(',')))
    obj_pos = tuple(map(float, parts[2].split(': ')[1].strip('()').split(',')))
    dist = tuple(map(float, parts[3].split(': ')[1].strip('()').split(',')))
    bearing = tuple(map(float, parts[4].split(': ')[1].strip('()').split(',')))
    delta = tuple(map(float, parts[5].split(': ')[1].strip('()').split(',')))

    return {
        'obj_id': obj_id,
        'cam_pos': cam_pos,
        'obj_pos': obj_pos,
        'dist': dist,
        'bearing': bearing,
        'delta': delta
    }

def compute_distance(cam_pos, obj_pos):
    return tuple(o - c for c, o in zip(cam_pos, obj_pos))

def compute_bearing(dist):
    yaw = math.atan2(dist[0], -dist[2]) * (180 / math.pi)
    pitch = math.atan2(dist[1], math.sqrt(dist[0]**2 + dist[2]**2)) * (180 / math.pi)
    return yaw, pitch

def check_output(log_line):
    data = parse_log(log_line)

    computed_dist = compute_distance(data['cam_pos'], data['obj_pos'])
    computed_bearing = compute_bearing(computed_dist)

    print(f"Parsed Data:")
    print(f"  Object ID: {data['obj_id']}")
    print(f"  Camera Position: {data['cam_pos']}")
    print(f"  Object Position: {data['obj_pos']}")
    print(f"  Reported Distance: {data['dist']}")
    print(f"  Computed Distance: {computed_dist}")
    print(f"  Reported Bearing: {data['bearing']}")
    print(f"  Computed Bearing: {computed_bearing}")
    print(f"  Reported Delta: {data['delta']}")

    dist_error = all(math.isclose(c, r, rel_tol=1e-5) for c, r in zip(computed_dist, data['dist']))
    bearing_error = all(math.isclose(c, r, rel_tol=1e-5) for c, r in zip(computed_bearing, data['bearing']))

    print(f"\nDistance check passed: {dist_error}")
    print(f"Bearing check passed: {bearing_error}")

log_line = "obj: 1, cam_pos: (0.0,0.0,-3.0), obj_pos: (8.0,0.0,-23.0), dist: (8.0,0.0,-20.0), bearing: (21.8,0.0), delta: (21.8,0.0,0.0)"
check_output(log_line)
