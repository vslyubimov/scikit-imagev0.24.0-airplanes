import base64

import numpy as np

from . import _marching_cubes_lewiner_luts as mcluts
from . import _marching_cubes_lewiner_cy
from ._marching_cubes_classic import _marching_cubes_classic


def marching_cubes(volume, level=None, *, spacing=(1., 1., 1.),
                   gradient_direction='descent', step_size=1,
                   allow_degenerate=True, method='lewiner', mask=None,
                   single_mesh=False):
    """Marching cubes algorithm to find surfaces in 3d volumetric data.

    In contrast with Lorensen et al. approach [2]_, Lewiner et
    al. algorithm is faster, resolves ambiguities, and guarantees
    topologically correct results. Therefore, this algorithm generally
    a better choice.

    Parameters
    ----------
    volume : (M, N, P) array
        Input data volume to find isosurfaces. Will internally be
        converted to float32 if necessary.
    level : float, optional
        Contour value to search for isosurfaces in `volume`. If not
        given or None, the average of the min and max of vol is used.
    spacing : length-3 tuple of floats, optional
        Voxel spacing in spatial dimensions corresponding to numpy array
        indexing dimensions (M, N, P) as in `volume`.
    gradient_direction : string, optional
        Controls if the mesh was generated from an isosurface with gradient
        descent toward objects of interest (the default), or the opposite,
        considering the *left-hand* rule.
        The two options are:
        * descent : Object was greater than exterior
        * ascent : Exterior was greater than object
    step_size : int, optional
        Step size in voxels. Default 1. Larger steps yield faster but
        coarser results. The result will always be topologically correct
        though.
    allow_degenerate : bool, optional
        Whether to allow degenerate (i.e. zero-area) triangles in the
        end-result. Default True. If False, degenerate triangles are
        removed, at the cost of making the algorithm slower.
    method: str, optional
        One of 'lewiner', 'lorensen' or '_lorensen'. Specify which of
        Lewiner et al. or Lorensen et al. method will be used. The
        '_lorensen' flag correspond to an old implementation that will
        be deprecated in version 0.19.
    mask : (M, N, P) array, optional
        Boolean array. The marching cube algorithm will be computed only on
        True elements. This will save computational time when interfaces
        are located within certain region of the volume M, N, P-e.g. the top
        half of the cube-and also allow to compute finite surfaces-i.e. open
        surfaces that do not end at the border of the cube.

    Returns
    -------
    verts : (V, 3) array
        Spatial coordinates for V unique mesh vertices. Coordinate order
        matches input `volume` (M, N, P). If ``allow_degenerate`` is set to
        True, then the presence of degenerate triangles in the mesh can make
        this array have duplicate vertices.
    faces : (F, 3) array
        Define triangular faces via referencing vertex indices from ``verts``.
        This algorithm specifically outputs triangles, so each face has
        exactly three indices.
    normals : (V, 3) array
        The normal direction at each vertex, as calculated from the
        data.
    values : (V, ) array
        Gives a measure for the maximum value of the data in the local region
        near each vertex. This can be used by visualization tools to apply
        a colormap to the mesh.

    See Also
    --------
    skimage.measure.mesh_surface_area
    skimage.measure.find_contours

    Notes
    -----
    The algorithm [1]_ is an improved version of Chernyaev's Marching
    Cubes 33 algorithm. It is an efficient algorithm that relies on
    heavy use of lookup tables to handle the many different cases,
    keeping the algorithm relatively easy. This implementation is
    written in Cython, ported from Lewiner's C++ implementation.

    To quantify the area of an isosurface generated by this algorithm, pass
    verts and faces to `skimage.measure.mesh_surface_area`.

    Regarding visualization of algorithm output, to contour a volume
    named `myvolume` about the level 0.0, using the ``mayavi`` package::

      >>>
      >> from mayavi import mlab
      >> verts, faces, _, _ = marching_cubes(myvolume, 0.0)
      >> mlab.triangular_mesh([vert[0] for vert in verts],
                              [vert[1] for vert in verts],
                              [vert[2] for vert in verts],
                              faces)
      >> mlab.show()

    Similarly using the ``visvis`` package::

      >>>
      >> import visvis as vv
      >> verts, faces, normals, values = marching_cubes(myvolume, 0.0)
      >> vv.mesh(np.fliplr(verts), faces, normals, values)
      >> vv.use().Run()

    To reduce the number of triangles in the mesh for better performance,
    see this `example
    <https://docs.enthought.com/mayavi/mayavi/auto/example_julia_set_decimation.html#example-julia-set-decimation>`_
    using the ``mayavi`` package.

    References
    ----------
    .. [1] Thomas Lewiner, Helio Lopes, Antonio Wilson Vieira and Geovan
           Tavares. Efficient implementation of Marching Cubes' cases with
           topological guarantees. Journal of Graphics Tools 8(2)
           pp. 1-15 (december 2003).
           :DOI:`10.1080/10867651.2003.10487582`
    .. [2] Lorensen, William and Harvey E. Cline. Marching Cubes: A High
           Resolution 3D Surface Construction Algorithm. Computer Graphics
           (SIGGRAPH 87 Proceedings) 21(4) July 1987, p. 163-170).
           :DOI:`10.1145/37401.37422`

    """

    if method == 'lewiner':
        return _marching_cubes_lewiner(volume, level, spacing,
                                       gradient_direction, step_size,
                                       allow_degenerate, use_classic=False,
                                       mask=mask, single_mesh=single_mesh)
    elif method == 'lorensen':
        return _marching_cubes_lewiner(volume, level, spacing,
                                       gradient_direction, step_size,
                                       allow_degenerate, use_classic=True,
                                       mask=mask, single_mesh=single_mesh)
    elif method == '_lorensen':
        if mask is not None:
            raise NotImplementedError(
                'Parameter `mask` is not implemented for method "_lorensen" '
                'and will be ignored.'
            )
        return _marching_cubes_classic(volume, level, spacing,
                                       gradient_direction)
    else:
        raise ValueError("method should be one of 'lewiner', 'lorensen' or "
                         "'_lorensen'.")


def _marching_cubes_lewiner(volume, level, spacing, gradient_direction,
                            step_size, allow_degenerate, use_classic, mask):
    """Lewiner et al. algorithm for marching cubes. See
    marching_cubes_lewiner for documentation.

    """

    # Check volume and ensure its in the format that the alg needs
    if not isinstance(volume, np.ndarray) or (volume.ndim != 3):
        raise ValueError('Input volume should be a 3D numpy array.')
    if volume.shape[0] < 2 or volume.shape[1] < 2 or volume.shape[2] < 2:
        raise ValueError("Input array must be at least 2x2x2.")
    volume = np.ascontiguousarray(volume,
                                  np.float32)  # no copy if not necessary

    # Check/convert other inputs:
    # level
    if level is None:
        level = 0.5 * (volume.min() + volume.max())
    else:
        level = float(level)
        if level < volume.min() or level > volume.max():
            raise ValueError("Surface level must be within volume data range.")
    # spacing
    if len(spacing) != 3:
        raise ValueError("`spacing` must consist of three floats.")
    # step_size
    step_size = int(step_size)
    if step_size < 1:
        raise ValueError('step_size must be at least one.')
    # use_classic
    use_classic = bool(use_classic)
    # extact single mesh
    single_mesh = bool(single_mesh)
    # Get LutProvider class (reuse if possible)
    L = _get_mc_luts()

    # Check if a mask array is passed
    if mask is not None:
        if not mask.shape == volume.shape:
            raise ValueError('volume and mask must have the same shape.')

    # Apply algorithm
    func = _marching_cubes_lewiner_cy.marching_cubes
    vertices, faces, normals, values = func(volume, level, L,
                                            step_size, use_classic, mask, 
                                            single_mesh)

    if not len(vertices):
        raise RuntimeError('No surface found at the given iso value.')

    # Output in z-y-x order, as is common in skimage
    vertices = np.fliplr(vertices)
    normals = np.fliplr(normals)

    # Finishing touches to output
    faces.shape = -1, 3
    if gradient_direction == 'descent':
        # MC implementation is right-handed, but gradient_direction is
        # left-handed
        faces = np.fliplr(faces)
    elif not gradient_direction == 'ascent':
        raise ValueError("Incorrect input %s in `gradient_direction`, see "
                         "docstring." % (gradient_direction))
    if not np.array_equal(spacing, (1, 1, 1)):
        vertices = vertices * np.r_[spacing]

    if allow_degenerate:
        return vertices, faces, normals, values
    else:
        fun = _marching_cubes_lewiner_cy.remove_degenerate_faces
        return fun(vertices.astype(np.float32), faces, normals, values)


def _to_array(args):
    shape, text = args
    byts = base64.decodebytes(text.encode('utf-8'))
    ar = np.frombuffer(byts, dtype='int8')
    ar.shape = shape
    return ar


# Map an edge-index to two relative pixel positions. The ege index
# represents a point that lies somewhere in between these pixels.
# Linear interpolation should be used to determine where it is exactly.
#   0
# 3   1   ->  0x
#   2         xx
EDGETORELATIVEPOSX = np.array([ [0,1],[1,1],[1,0],[0,0], [0,1],[1,1],[1,0],[0,0], [0,0],[1,1],[1,1],[0,0] ], 'int8')
EDGETORELATIVEPOSY = np.array([ [0,0],[0,1],[1,1],[1,0], [0,0],[0,1],[1,1],[1,0], [0,0],[0,0],[1,1],[1,1] ], 'int8')
EDGETORELATIVEPOSZ = np.array([ [0,0],[0,0],[0,0],[0,0], [1,1],[1,1],[1,1],[1,1], [0,1],[0,1],[0,1],[0,1] ], 'int8')


def _get_mc_luts():
    """ Kind of lazy obtaining of the luts.
    """
    if not hasattr(mcluts, 'THE_LUTS'):

        mcluts.THE_LUTS = _marching_cubes_lewiner_cy.LutProvider(
                EDGETORELATIVEPOSX, EDGETORELATIVEPOSY, EDGETORELATIVEPOSZ,

                _to_array(mcluts.CASESCLASSIC), _to_array(mcluts.CASES),

                _to_array(mcluts.TILING1), _to_array(mcluts.TILING2), _to_array(mcluts.TILING3_1), _to_array(mcluts.TILING3_2),
                _to_array(mcluts.TILING4_1), _to_array(mcluts.TILING4_2), _to_array(mcluts.TILING5), _to_array(mcluts.TILING6_1_1),
                _to_array(mcluts.TILING6_1_2), _to_array(mcluts.TILING6_2), _to_array(mcluts.TILING7_1),
                _to_array(mcluts.TILING7_2), _to_array(mcluts.TILING7_3), _to_array(mcluts.TILING7_4_1),
                _to_array(mcluts.TILING7_4_2), _to_array(mcluts.TILING8), _to_array(mcluts.TILING9),
                _to_array(mcluts.TILING10_1_1), _to_array(mcluts.TILING10_1_1_), _to_array(mcluts.TILING10_1_2),
                _to_array(mcluts.TILING10_2), _to_array(mcluts.TILING10_2_), _to_array(mcluts.TILING11),
                _to_array(mcluts.TILING12_1_1), _to_array(mcluts.TILING12_1_1_), _to_array(mcluts.TILING12_1_2),
                _to_array(mcluts.TILING12_2), _to_array(mcluts.TILING12_2_), _to_array(mcluts.TILING13_1),
                _to_array(mcluts.TILING13_1_), _to_array(mcluts.TILING13_2), _to_array(mcluts.TILING13_2_),
                _to_array(mcluts.TILING13_3), _to_array(mcluts.TILING13_3_), _to_array(mcluts.TILING13_4),
                _to_array(mcluts.TILING13_5_1), _to_array(mcluts.TILING13_5_2), _to_array(mcluts.TILING14),

                _to_array(mcluts.TEST3), _to_array(mcluts.TEST4), _to_array(mcluts.TEST6),
                _to_array(mcluts.TEST7), _to_array(mcluts.TEST10), _to_array(mcluts.TEST12),
                _to_array(mcluts.TEST13), _to_array(mcluts.SUBCONFIG13),
                )

    return mcluts.THE_LUTS
