import math
import array as _arr

# Pure Python port of the dsplib C module.

def _mat3mul(a, b):
  c = [0.0] * 9
  for i in range(3):
    for j in range(3):
      s = 0.0
      for k in range(3):
        s += a[i*3+k] * b[k*3+j]
      c[i*3+j] = s
  return c


def set_transform_matrix_4x4(matrix, rotation, position, scale):
  rx, ry, rz = rotation[0], rotation[1], rotation[2]
  tx, ty, tz = position[0], position[1], position[2]
  sclx, scly, sclz = scale[0], scale[1], scale[2]
  cx, sx = math.cos(rx), math.sin(rx)
  cy, sy = math.cos(ry), math.sin(ry)
  cz, sz = math.cos(rz), math.sin(rz)

  # Rotation matrices (row-major 3x3)
  rzm = [cz, -sz, 0,  sz, cz, 0,  0, 0, 1]
  rym = [cy, 0, sy,   0, 1, 0,   -sy, 0, cy]
  rxm = [1, 0, 0,   0, cx, -sx,   0, sx, cx]

  # Combined rotation: Ry * Rx * Rz
  r = _mat3mul(_mat3mul(rym, rxm), rzm)

  # Apply per-axis scale to each column
  for i in range(9):
    col = i % 3
    r[i] *= (sclx if col == 0 else scly if col == 1 else sclz)

  matrix[0]  = r[0]; matrix[1]  = r[1]; matrix[2]  = r[2];  matrix[3]  = 0.0
  matrix[4]  = r[3]; matrix[5]  = r[4]; matrix[6]  = r[5];  matrix[7]  = 0.0
  matrix[8]  = r[6]; matrix[9]  = r[7]; matrix[10] = r[8];  matrix[11] = 0.0
  matrix[12] = tx;   matrix[13] = ty;   matrix[14] = tz;    matrix[15] = 1.0


def set_transform_matrix_3x3(matrix, rotation, position, scale):
  c, s = math.cos(rotation), math.sin(rotation)
  sx, sy = scale[0], scale[1]
  tx, ty = position[0], position[1]
  matrix[0] = c*sx;  matrix[1] = -s*sy; matrix[2] = tx
  matrix[3] = s*sx;  matrix[4] =  c*sy; matrix[5] = ty
  matrix[6] = 0;     matrix[7] = 0;     matrix[8] = 1.0


def matrix_mul_f32(A, B, m, n, k, C):
  for i in range(m):
    for j in range(k):
      v = 0.0
      for p in range(n):
        v += A[i*n+p] * B[p*k+j]
      C[i*k+j] = v


def matrix_mul_s16(A, B, m, n, k, C, shift):
  scale = 1 << shift
  for i in range(m):
    for j in range(k):
      v = 0
      for p in range(n):
        v += A[i*n+p] * B[p*k+j]
      C[i*k+j] = v >> shift


def project_3d_indexed(matrix, verts, indices, normals, light,
                       num_faces, num_verts, fov, cx, cy,
                       out_poly, out_dither, out_depths,
                       temp_verts, temp_norms):
  # Transform vertices
  for i in range(num_verts):
    x, y, z = verts[i*3], verts[i*3+1], verts[i*3+2]
    tx = matrix[0]*x + matrix[4]*y + matrix[8]*z  + matrix[12]
    ty = matrix[1]*x + matrix[5]*y + matrix[9]*z  + matrix[13]
    tz = matrix[2]*x + matrix[6]*y + matrix[10]*z + matrix[14]
    temp_verts[i*3] = tx
    temp_verts[i*3+1] = ty
    temp_verts[i*3+2] = tz

  # Normalize the light direction once.
  llen = math.sqrt(light[0]**2 + light[1]**2 + light[2]**2) or 1.0
  lx, ly, lz = light[0]/llen, light[1]/llen, light[2]/llen

  for f in range(num_faces):
    i0, i1, i2 = indices[f*3], indices[f*3+1], indices[f*3+2]
    # Transform normal (matrix carries uniform scale, so just renormalize)
    nx, ny, nz = normals[f*3], normals[f*3+1], normals[f*3+2]
    tnx = matrix[0]*nx + matrix[4]*ny + matrix[8]*nz
    tny = matrix[1]*nx + matrix[5]*ny + matrix[9]*nz
    tnz = matrix[2]*nx + matrix[6]*ny + matrix[10]*nz
    # Backface cull (uniform positive scale preserves the sign of tnz)
    if tnz >= 0:
      out_dither[f] = -1
      continue
    nlen = math.sqrt(tnx*tnx + tny*tny + tnz*tnz) or 1.0
    tnx /= nlen; tny /= nlen; tnz /= nlen
    # Diffuse + ambient so visible faces are never fully black
    dot = -(lx*tnx + ly*tny + lz*tnz)
    shade = 0.25 + 0.75 * max(0.0, dot)
    out_dither[f] = max(1, min(16, int(shade * 16)))
    # Project vertices
    for vi, idx in enumerate((i0, i1, i2)):
      tx = temp_verts[idx*3]
      ty = temp_verts[idx*3+1]
      tz = temp_verts[idx*3+2]
      if tz == 0: tz = 0.001
      px = int(tx * fov / (-tz) + cx)
      py = int(ty * fov / (-tz) + cy)
      out_poly[f*6+vi] = px
      out_poly[f*6+3+vi] = py
    # Depth
    z_avg = (temp_verts[i0*3+2] + temp_verts[i1*3+2] + temp_verts[i2*3+2]) / 3
    out_depths[f] = int(z_avg * 1024)


def project_2d_indexed(matrix, verts, indices, colors, light,
                       num_faces, num_verts, cx, cy,
                       out_poly, out_dither, temp_verts):
  for i in range(num_verts):
    x, y = verts[i*2], verts[i*2+1]
    tx = matrix[0]*x + matrix[3]*y + matrix[6]
    ty = matrix[1]*x + matrix[4]*y + matrix[7]
    temp_verts[i*2] = tx
    temp_verts[i*2+1] = ty

  for f in range(num_faces):
    i0, i1, i2 = indices[f*3], indices[f*3+1], indices[f*3+2]
    for vi, idx in enumerate((i0, i1, i2)):
      out_poly[f*6+vi]   = int(temp_verts[idx*2] + cx)
      out_poly[f*6+3+vi] = int(temp_verts[idx*2+1] + cy)
    c = (colors[i0] + colors[i1] + colors[i2]) / 3 * light
    out_dither[f] = max(0, min(16, int(c)))


def sort_indices(indices, depths, start_id=None):
  n = len(indices)
  if start_id is not None:
    for i in range(n):
      indices[i] = start_id + i
  # Sort indices by depth descending (painter's algorithm)
  idx_list = list(range(n))
  idx_list.sort(key=lambda i: -depths[i])
  tmp = list(indices)
  for i, v in enumerate(idx_list):
    indices[i] = tmp[v]
