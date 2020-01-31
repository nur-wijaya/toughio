from __future__ import division, with_statement, unicode_literals

import logging

import itertools

import numpy

__all__ = [
    "read",
    "write",
]


meshio_data = {"avsucd:material", "flac3d:zone", "gmsh:physical", "medit:ref", "tough:material"}


def read(filename):
    """
    Read TOUGH MESH file is not supported yet. MESH file does not store
    any geometrical information except node centers.
    """
    raise NotImplementedError(
        "Reading TOUGH MESH file is not supported."
    )


def write(filename, mesh, nodal_distance):
    """
    Write TOUGH MESH file.
    """
    assert nodal_distance in {"line", "orthogonal"}

    nodes = numpy.concatenate(mesh.centers)
    labels = numpy.concatenate(mesh.labels)
    with open(filename, "w") as f:
        _write_eleme(f, mesh, labels, nodes)
        _write_conne(f, mesh, labels, nodes, nodal_distance)


def block(keyword):
    """
    Decorator for block writing functions.
    """

    def decorator(func):
        from functools import wraps

        header = "----1----*----2----*----3----*----4----*----5----*----6----*----7----*----8"

        @wraps(func)
        def wrapper(f, *args):
            f.write("{}{}\n".format(keyword, header))
            func(f, *args)
            f.write("\n")

        return wrapper

    return decorator


@block("ELEME")
def _write_eleme(f, mesh, labels, nodes):
    """
    Write ELEME block.
    """
    # Define materials and volumes
    rocks = _get_rocks(mesh)
    volumes = numpy.concatenate(mesh.volumes)

    # Apply time-independent Dirichlet boundary conditions
    if "boundary_condition" in mesh.cell_data.keys():
        bc = numpy.concatenate(mesh.cell_data["boundary_condition"])
        volumes *= numpy.where(bc, 1.0e50, 1.0)

    # Write ELEME block
    fmt = "{:5.5}{:>5}{:>5}{:>5}{:10.4e}{:>10}{:>10}{:10.3e}{:10.3e}{:10.3e}\n"
    iterables = zip(labels, rocks, volumes, nodes)
    for label, rock, volume, node in iterables:
        record = fmt.format(
            label,  # ID
            "",  # NSEQ
            "",  # NADD
            rock,  # MAT
            volume,  # VOLX
            "",  # AHTX
            "",  # PMX
            node[0],  # X
            node[1],  # Y
            node[2],  # Z
        )
        f.write(record)


def _get_rocks(mesh):
    """
    Returns material type for each cell in mesh.
    """
    mat_data = None
    for k in mesh.cell_data.keys():
        if k in meshio_data:
            mat_data = k
            break

    if mat_data:
        rocks = numpy.concatenate(mesh.cell_data[mat_data])
        if mesh.field_data:
            field_data = {v[0]: k for k, v in mesh.field_data.items() if v[1] == 3}
            rocks = [field_data[rock] for rock in rocks]
    else:
        rocks = numpy.ones(mesh.n_cells, dtype=int)
    return rocks


@block("CONNE")
def _write_conne(f, mesh, labels, nodes, nodal_distance):
    """
    Write CONNE block.
    """
    # Define points, connections and normalized gravity vector
    points = mesh.points
    neighbors = numpy.concatenate(mesh.connectivity)
    g_vec = numpy.array([0., 0., 1.])

    # Define parameters related to faces
    faces = numpy.concatenate(mesh.faces)
    faces_dict, faces_cell = _get_faces(faces)
    face_normals, face_areas = _get_face_normals_areas(mesh, faces_dict, faces_cell)

    # Define boundary elements
    bc = (
        numpy.concatenate(mesh.cell_data["boundary_condition"])
        if "boundary_condition" in mesh.cell_data.keys()
        else numpy.zeros(mesh.n_cells)
    )

    # Define unique connection variables
    cell_list = set()
    clabels, centers, int_points, int_normals, areas, bounds = [], [], [], [], [], []
    for i, neighbor in enumerate(neighbors):
        if (neighbor >= 0).any():
            for iface, j in enumerate(neighbor):
                if j >= 0 and j not in cell_list:
                    # Label
                    clabels.append("{:5.5}{:5.5}".format(labels[i], labels[j]))

                    # Nodal points
                    centers.append([nodes[i], nodes[j]])

                    # Common interface defined by single point and normal vector
                    face = faces[i,iface]
                    int_points.append(points[face[face >= 0][0]])
                    int_normals.append(face_normals[i][iface])

                    # Area of common face
                    areas.append(face_areas[i][iface])

                    # Boundary conditions
                    bounds.append([bc[i], bc[j]])
        else:
            logging.warning(
                "\nElement '{}' is not connected to the grid.".format(labels[i])
            )
        cell_list.add(i)

    centers = numpy.array(centers)
    int_points = numpy.array(int_points)
    int_normals = numpy.array(int_normals)
    bounds = numpy.array(bounds)

    # Calculate remaining variables not available in itasca module
    lines = numpy.diff(centers, axis=1)[:, 0]
    isot = _isot(lines)
    angles = numpy.dot(lines, g_vec) / numpy.linalg.norm(lines, axis=1)

    if nodal_distance == "line":
        fp = _intersection_line_plane(centers[:, 0], lines, int_points, int_normals)
        d1 = numpy.where(bounds[:, 0], 1.0e-9, numpy.linalg.norm(centers[:, 0] - fp, axis=1))
        d2 = numpy.where(bounds[:, 1], 1.0e-9, numpy.linalg.norm(centers[:, 1] - fp, axis=1))
    elif nodal_distance == "orthogonal":
        d1 = _distance_point_plane(centers[:, 0], int_points, int_normals, bounds[:, 0])
        d2 = _distance_point_plane(centers[:, 1], int_points, int_normals, bounds[:, 1])
    
    # Write CONNE block
    fmt = "{:10.10}{:>5}{:>5}{:>5}{:>5g}{:10.4e}{:10.4e}{:10.4e}{:10.3e}\n"
    iterables = zip(clabels, isot, d1, d2, areas, angles)
    for label, isot, d1, d2, area, angle in iterables:
        record = fmt.format(
            label,  # ID1-ID2
            "",  # NSEQ
            "",  # NAD1
            "",  # NAD2
            isot,  # ISOT
            d1,  # D1
            d2,  # D2
            area,  # AREAX
            angle,  # BETAX
        )
        f.write(record)


def _get_faces(faces):
    """
    Return a face dictionary.
    """
    faces_dict = {"triangle": [], "quad": []}
    faces_cell = {"triangle": [], "quad": []}
    numvert_to_face_type = {3: "triangle", 4: "quad"}

    for i, face in enumerate(faces):
        numvert = (face >= 0).sum(axis=-1)
        for f, n in zip(face, numvert):
            if n > 0:
                face_type = numvert_to_face_type[n]
                faces_dict[face_type].append(f[:n])
                faces_cell[face_type].append(i)
    
    # Stack arrays or remove empty cells
    faces_dict = {
        k: numpy.sort(numpy.vstack(v), axis = 1) for k, v in faces_dict.items() if len(v)
    }
    faces_cell = {k: v for k, v in faces_cell.items() if len(v)}

    return faces_dict, faces_cell


def _get_triangle_normals(mesh, faces, islice = [0, 1, 2]):
    """
    Calculate normal vectors of triangular faces.
    """
    def cross(a, b):
        return a[:,[1,2,0]]*b[:,[2,0,1]] - a[:,[2,0,1]]*b[:,[1,2,0]]
    
    triangles = numpy.vstack([c[islice] for c in faces])
    triangles = mesh.points[triangles]

    return cross(
        triangles[:,1] - triangles[:,0],
        triangles[:,2] - triangles[:,0],
    )


def _get_face_normals_areas(mesh, faces_dict, faces_cell):
    """
    Calculate face normal vectors and areas.
    """
    # Face normal vectors
    normals = numpy.concatenate([
        _get_triangle_normals(mesh, v) for k, v in faces_dict.items()
    ])
    normals_mag = numpy.linalg.norm(normals, axis = -1)
    normals /= normals_mag[:,None]

    # Face areas
    areas = numpy.array(normals_mag)
    if len(faces_dict["quad"]):
        tmp = numpy.concatenate([
            _get_triangle_normals(mesh, v, [0, 2, 3])
            if k == "quad"
            else numpy.zeros((len(v), 3))
            for k, v in faces_dict.items()
        ])
        areas += numpy.linalg.norm(tmp, axis = -1)
    areas *= 0.5

    # Reorganize outputs
    face_normals = [[] for _ in range(mesh.n_cells)]
    face_areas = [[] for _ in range(mesh.n_cells)]
    iface = numpy.concatenate([v for v in faces_cell.values()])
    for i, normal, area in zip(iface, normals, areas):
        face_normals[i].append(normal)
        face_areas[i].append(area)

    return face_normals, face_areas


def _intersection_line_plane(center, lines, int_points, int_normals):
    """
    Calculate intersection point between a line defined by a point and a
    direction vector and a plane defined by one point and a normal vector.
    """
    tmp = _dot(int_points - center, int_normals) / _dot(lines, int_normals)
    return center + lines * tmp[:, None]


def _distance_point_plane(center, int_points, int_normals, mask):
    """
    Calculate orthogonal distance of a point to a plane defined by one
    point and a normal vector.
    """
    return numpy.where(mask, 1.0e-9, numpy.abs(_dot(center - int_points, int_normals)))


def _isot(lines):
    """
    Determine anisotropy direction given the direction of the line
    connecting the cell centers.
    Note
    ----
    It always returns 1 if the connection line is not colinear with X, Y or Z.
    """
    mask = lines != 0.0
    return numpy.where(mask.sum(axis=1) == 1, mask.argmax(axis=1) + 1, 1)


def _dot(A, B):
    """
    Custom dot product when arrays A and B have the same shape.
    """
    return (A * B).sum(axis=1)