# -*- coding: utf-8 -*-

# MIT license
#
# Copyright (C) 2018-2021 by Dave Vandenbout.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
"""
Arrange footprints based on the schematic hierarchy of the design.

Vendored from HierPlace v1.1.0 by Dave Vandenbout (MIT) --
https://github.com/devbisme/HierPlace -- with the following changes for
headless use inside an MCP server:
  * removed the hardcoded `sys.path.append('/usr/lib/python3/dist-packages')`
  * removed the pcbnew GUI `ActionPlugin` subclass + `.register()` call
    (it asserts `PgmOrNull()` when imported outside the pcbnew GUI)
  * guarded the trailing `Refresh()` so it is a no-op headless

The placement algorithm (group_modules / pack / hier_place) is unchanged.
"""

from collections import defaultdict

import builtins

from pcbnew import *  # noqa: F401,F403  (Module/board API used unqualified, as upstream)

try:
    KICAD_VERSION = int(Version().split(".")[0])
except NameError:
    # No version function, so assume this is KiCad 5.
    KICAD_VERSION = 5

# Extra spacing placed around bounding boxes of modules and groups of modules
# to provide visual separation.
MODULE_SPACING = 350000
GROUP_SPACING = 5 * MODULE_SPACING


class Module(object):
    '''A class to provide extra functions for PCBNEW MODULES.'''

    def __init__(self, pcbnew_module):
        '''Create a Module instance that stores a PCBNEW MODULE instance.'''
        self.m = pcbnew_module

    @property
    def ref(self):
        '''Return a string with the module's reference id, such as "R3".'''
        return self.m.GetReference()

    @property
    def hier_level(self):
        '''Return a string with the hierarchical level of the module.'''
        try:
            path_parts = self.m.GetPath().AsString().split('/')
        except AttributeError:
            path_parts = self.m.GetPath().split('/')
        return '/'.join(path_parts[:-1])

    @property
    def bbox(self):
        '''Return an EDA_RECT or BOX2I with the bounding box of the module.'''
        try:
            bb = self.m.GetBoundingBox()
        except AttributeError:
            bb = self.m.GetFootprintRect()
        bb.Inflate(MODULE_SPACING)
        return bb

    def touches(self, module):
        '''Return True if the given module intersects this module.'''
        bb1 = self.bbox
        # Slightly shrink the bounding box so two modules that abut each other
        # won't be reported as touching.
        bb1.Inflate(-1)
        return bb1.Intersects(module.bbox)

    @property
    def center(self):
        '''Return wxPoint containing the centroid of the module.'''
        return self.bbox.GetCenter()

    @property
    def tl_corner(self):
        '''Return wxPoint containing the top-left corner of the module.'''
        bb = self.bbox
        return wxPoint(bb.GetLeft(), bb.GetTop())

    @property
    def br_corner(self):
        '''Return wxPoint containing the bottom-right corner of the module.'''
        bb = self.bbox
        return wxPoint(bb.GetRight(), bb.GetBottom())

    @property
    def bl_corner(self):
        '''Return wxPoint containing the bottom-left corner of the module.'''
        bb = self.bbox
        return wxPoint(bb.GetLeft(), bb.GetBottom())

    @property
    def w(self):
        '''Return the width of the module.'''
        return self.bbox.GetWidth()

    @property
    def h(self):
        '''Return the height of the module.'''
        return self.bbox.GetHeight()

    @property
    def area(self):
        '''Return the area of the module's bounding box.'''
        return self.bbox.GetArea()

    @property
    def selected(self):
        return self.m.IsSelected()

    @property
    def locked(self):
        '''Return True if the module is locked in place.'''
        return self.m.IsLocked()

    def move(self, dx, dy):
        '''Move a module by the given distance in the X and Y directions.'''
        if not self.locked:
            if KICAD_VERSION >= 7:
                self.m.Move(VECTOR2I(dx, dy))
            else:
                self.m.Move(wxPoint(dx, dy))

    def set_bl_position(self, point):
        '''Set the position of the module's bottom-left corner to the given (X,Y) coordinate.'''
        if not self.locked:
            mv = point - self.bl_corner  # Get vector from BL corner to desired point.
            self.move(mv.x, mv.y)


class ModuleGroup(list, Module):
    '''A class that stores modules or module-groups as a list and also acts like a module.'''

    def __init__(self, *args):
        super(ModuleGroup, self).__init__(*args)

    @property
    def ref(self):
        '''Return a string composed of the reference ids of the modules it contains.'''
        return '[' + ','.join([m.ref for m in self]) + ']'

    @property
    def hier_level(self):
        '''Return a string with the hierarchical level of the module group.'''
        return '/'.join((self[0].hier_level.split('/'))[:-1])

    @property
    def bbox(self):
        '''Return an EDA_RECT or BOX2I with the bounding box of the group of modules.'''
        try:
            bbox = BOX2I()
        except NameError:
            bbox = EDA_RECT()
        bbox.Move(self[0].center)
        for module in self:
            bbox.Merge(module.bbox)
        bbox.Inflate(GROUP_SPACING)
        return bbox

    @property
    def locked(self):
        '''Alsways return False because a module group never contains any locked modules.'''
        return False

    def move(self, dx, dy):
        '''Move all the modules in a group by the given distance in the X and Y directions.'''
        if not self.locked:
            for m in self:
                m.move(dx, dy)


def group_modules(modules):
    '''
    Create a dictionary where each entry contains the modules at that level of the hierarchy.
    '''
    groups = defaultdict(ModuleGroup)
    for m in modules:
        if not m.locked:
            # Add each unlocked module to the group at the same position of the hierarchy.
            groups[m.hier_level].append(m)
    return groups


def pack(group):
    '''
    Pack a group of modules into a tight formation.
    '''

    # Packing starts with the module that's largest in area. The top-left (TL)
    # and bottom-right (BR) corners of that module become potential points where
    # the lower-left corner of the next-largest module can be placed.
    # The point is chosen based upon how much the bounding box of the
    # currently-placed modules will expand. When a module is placed,
    # the placement point is removed and the TL and BR corners
    # of the just-placed module are added to the list of points.
    # This proceeds until all the modules are placed in order of decreasing area.

    # Create an empty group to store the modules as they are packed.
    packed_modules = ModuleGroup()

    # Storage for the potential places where a module can be inserted.
    placement_pts = []  # Starts off empty.

    # Iterate through the modules in order of decreasing area, placing each one
    # where it will keep the group within a small area.
    for module in sorted(group, key=lambda m: -m.area):

        # Skip over locked modules since they can't be moved.
        if module.locked:
            continue

        # Add the module to the packed group. (It still needs to be positioned.)
        packed_modules.append(module)

        # If there are potential placement points, then go through them looking
        # for the one that gives the best packing of the currently-placed modules.
        # The only time this is not done will be for the very first module in the
        # group which will serve as the anchor the others will gather around.
        if placement_pts:

            # Iterate through the potential placement points and pick the one that
            # least expands the total bounding box.
            best_pt, smallest_size = None, float('inf')
            for pt in placement_pts:

                # Move module bottom-left corner to the placement point.
                module.set_bl_position(pt)

                # Check to see if the module touches any of the other modules in the packed group.
                for pm in packed_modules:
                    if pm is module:
                        # Don't check for intersections between the module and itself.
                        continue
                    if module.touches(pm):
                        # Discard this placement point if the module touches one of the others.
                        break
                else:
                    # If we got here, the placement point doesn't cause this module
                    # to touch any of the others. Now check the size of the resulting
                    # group of modules. The size is the sum of the height and width
                    # plus the difference between the height and width. This
                    # measure will attempt to keep the area small and square-like.
                    size = packed_modules.h + packed_modules.w + builtins.abs(
                        packed_modules.h - packed_modules.w)

                    # If this configuration is the smallest so far, store it.
                    if size <= smallest_size:
                        smallest_size = size
                        best_pt = pt

            # Place the module at the best placement point that was found.
            module.set_bl_position(best_pt)

            # Remove the placement point since no other module can be placed there, now.
            placement_pts.remove(best_pt)

        # Add the top-left and bottom-right corners of the just-placed module
        # to the list of potential placement points.
        placement_pts.extend([module.tl_corner, module.br_corner])


def hier_place(brd=None):
    '''
    Remove overlaps of board parts while respecting their hierarchy.
    '''

    brd = brd or GetBoard()
    try:
        modules = [Module(m) for m in brd.GetFootprints()]
    except AttributeError:
        modules = [Module(m) for m in brd.GetModules()]

    # Get modules in the PCB that are selected.
    # If no modules are selected, then operate on all the modules in the PCB.
    selected_modules = [m for m in modules if m.selected] or modules

    # Place the modules into groups based on hierarchy.
    groups = group_modules(selected_modules)

    # Pack all the modules in each group. Then move up a level in the hierarchy
    # and pack a group of packed modules into another packing. Proceed upward
    # until all the levels of the hierarchy have been packed.
    while True:

        # Pack the members of each group.
        for group in groups.values():
            pack(group)

        # If there's only one group left, then all the hierarchical levels have
        # been packed, so we're done.
        if len(groups) <= 1:
            break

        # Otherwise, collect the packed groups into groups at the next level
        # of hierarchy and repeat the loop.
        groups = group_modules(groups.values())

    # Refresh the GUI if one is attached; a no-op when running headless.
    try:
        Refresh()
    except Exception:
        pass

    return len(selected_modules)
