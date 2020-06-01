#!/usr/bin/env python

import os.path
import signal
import rospy
from geometry_msgs.msg import Pose, Quaternion, Point
from std_msgs.msg import Header
from nav_msgs.msg import MapMetaData, OccupancyGrid
from tf.transformations import euler_from_quaternion, quaternion_from_euler
import numpy as np
from PIL import Image as PILImage, ImageDraw as PILImageDraw, ImageTk
from Tkinter import *
import tkFileDialog
import cv2
from cv_bridge import CvBridge
import yaml

from utils import CoordinateConverter


class CanvasMode( object ):

  def __init__( self, canvas ):
    pass

  def click1( self, event ):
    pass

  def click1_motion( self, event ):
    pass

  def click1_off( self, event ):
    pass

  def double_click1( self, event ):
    pass


class IdleMode( CanvasMode ):
  pass


class SetRobotPoseMode( CanvasMode ):

  def __init__( self, canvas, set_initial_pose_cb ):
    self.canvas = canvas
    self.set_initial_pose_cb = set_initial_pose_cb
    self.x = 0
    self.y = 0
    self.yaw = 0

  def click1( self, event ):
    canvasx = self.canvas.canvasx( event.x )
    canvasy = self.canvas.canvasy( event.y )
    self.x, self.y, self.yaw = self.get_current_pose()
    current_tag = self.canvas.itemcget( CURRENT, 'tags' ).split( ' ' )[0]
    if current_tag.startswith( 'robot' ):
      coords = self.canvas.coords( 'robot' )
      radius = ( coords[0] - coords[2] )/2
      coords = [canvasx-radius, canvasy-radius, canvasx+radius, canvasy+radius]
      self.canvas.coords( 'robot', *coords )
      coords = self.canvas.coords( 'robot_direction' )
      deltax = canvasx - coords[0]
      deltay = canvasy - coords[1]
      coords[0] += deltax
      coords[1] += deltay
      coords[2] += deltax
      coords[3] += deltay
      self.canvas.coords( 'robot_direction', *coords )
      self.x = canvasx
      self.y = canvasy
    else:
      coords = self.canvas.coords( 'robot' )
      radius = ( coords[2] - coords[0] )/2
      x = coords[0] + radius
      y = coords[1] + radius
      yaw = np.arctan2( -( canvasy - y), canvasx - x )
      x1 = int( x + radius * np.cos( yaw ) )
      y1 = int( y - radius * np.sin( yaw ) )
      coords = [x, y, x1, y1]
      self.canvas.coords( 'robot_direction', *coords )
      self.yaw = yaw

  def click1_motion( self, event ):
    canvasx = self.canvas.canvasx( event.x )
    canvasy = self.canvas.canvasy( event.y )
    current_tag = self.canvas.itemcget( CURRENT, 'tags' ).split( ' ' )[0]
    if current_tag.startswith( 'robot' ):
      deltax = canvasx - self.x
      deltay = canvasy - self.y
      coords = self.canvas.coords( 'robot' )
      coords[0] += deltax
      coords[1] += deltay
      coords[2] += deltax
      coords[3] += deltay
      self.canvas.coords( 'robot', *coords )
      coords = self.canvas.coords( 'robot_direction' )
      coords[0] += deltax
      coords[1] += deltay
      coords[2] += deltax
      coords[3] += deltay
      self.canvas.coords( 'robot_direction', *coords )
      self.x = canvasx
      self.y = canvasy
    else:
      coords = self.canvas.coords( 'robot' )
      radius = ( coords[2] - coords[0] )/2
      x = coords[0] + radius
      y = coords[1] + radius
      yaw = np.arctan2( -( canvasy - y), canvasx - x )
      x1 = int( x + radius * np.cos( yaw ) )
      y1 = int( y - radius * np.sin( yaw ) )
      coords = [x, y, x1, y1]
      self.canvas.coords( 'robot_direction', *coords )
      self.yaw = yaw

  def click1_off( self, event ):
    self.set_initial_pose_cb( [self.x, self.y, self.yaw] )

  def get_current_pose( self ):
    coords = self.canvas.coords( 'robot' )
    radius = ( coords[2] - coords[0] )/2
    x = coords[0] + radius
    y = coords[1] + radius
    coords = self.canvas.coords( 'robot_direction' )
    yaw = np.arctan2( -(coords[3] - coords[1]), coords[2] - coords[0] )
    return x, y, yaw


class AddWallMode( CanvasMode ):

  def __init__( self, canvas, id_offset = 0 ):
    self.canvas = canvas
    self.x = 0
    self.y = 0
    self.id_offset = id_offset
    self.current_tag = ''

  def click1( self, event ):
    self.x = self.canvas.canvasx( event.x )
    self.y = self.canvas.canvasy( event.y )
    self.current_tag = 'wall_' + str( self.id_offset )
    self.canvas.create_line( self.x, self.y, self.x, self.y, width = 3, fill = 'black', tags = self.current_tag )

  def click1_motion( self, event ):
    canvasx = self.canvas.canvasx( event.x )
    canvasy = self.canvas.canvasy( event.y )
    deltax = canvasx - self.x
    deltay = canvasy - self.y
    coords = self.canvas.coords( self.current_tag )
    coords[2] += deltax
    coords[3] += deltay
    self.canvas.coords( self.current_tag, *coords )
    self.x = canvasx
    self.y = canvasy

  def click1_off( self, event ):
    self.id_offset += 1

  def reset( self ):
    self.id_offset = 0


class DeleteWallMode( CanvasMode ):

  def __init__( self, canvas ):
    self.canvas = canvas

  def click1( self, event ):
    current_tag = self.canvas.itemcget( CURRENT, 'tags' ).split( ' ' )[0]
    if current_tag.startswith( 'wall_' ):
      self.canvas.delete( current_tag )


class WorldStateGUI( Frame ):

  def __init__( self, width = 500, height = 290, resolution = 0.01 ):
    self.wall_thick = 3
    self.width = width + 2 * self.wall_thick
    self.height = height + 2 * self.wall_thick
    self.resolution = resolution # [m/pix]
    self.robot_diameter = 0.355 # [m]
    self.robot_radio = self.robot_diameter / 2.0 # [m]
    self.robot_radio_pix = int( self.robot_radio / self.resolution )
    self.converter = CoordinateConverter( 0.0, self.height * self.resolution, self.resolution )
    self.cv_bridge = CvBridge()

    self.root = Tk()
    self.root.geometry( '%dx%d' % (self.width, self.height) )
    self.root.title( 'World State' )
    self.root.resizable( False, False )
    Frame.__init__( self, self.root, width = self.width, height = self.height )
    self.grid( row = 0, column = 0 )

    menubar = Menu( self.master )
    self.master.config( menu = menubar )
    fileMenu = Menu( menubar )
    fileMenu.add_command( label = "Open map ...", command = self.open_map )
    fileMenu.add_command( label = "Exit", command = self.on_exit )
    menubar.add_cascade( label = "File", menu = fileMenu )
    toolsMenu = Menu( menubar )
    toolsMenu.add_command( label = "Reset", command = self.reset_state )
    menubar.add_cascade( label = "Tools", menu = toolsMenu )

    npimage = self.add_margin( 255 * np.ones( (height, width), dtype = np.uint8 ) )
    self.canvas = Canvas( self, width = self.width, height = self.height, bg = '#FFFFFF' )
    self.canvas.pack( side = LEFT, expand = True, fill = BOTH )
    self.canvas.pilimage = PILImage.fromarray( npimage )
    self.canvas.bgimage = ImageTk.PhotoImage( self.canvas.pilimage )
    self.canvas.create_image( 0, 0, anchor = NW, image = self.canvas.bgimage, tags = 'backgroundimg' )

    self.canvas.bind( '<ButtonPress-1>', self.click1 )
    self.canvas.bind( '<ButtonRelease-1>', self.click1_off )
    self.canvas.bind( '<B1-Motion>', self.click1_motion )
    self.canvas.bind( '<Key>', self.key_pressed )
    self.canvas.configure( cursor = 'left_ptr' )
    self.canvas.focus_set()

    self.statem = dict()
    self.statem['idle_mode'] = IdleMode( self.canvas )
    self.statem['set_robot_pose_mode'] = SetRobotPoseMode( self.canvas, self.send_initial_pose )
    self.statem['add_wall_mode'] = AddWallMode( self.canvas )
    self.statem['delete_wall_mode'] = DeleteWallMode( self.canvas )
    self.cstate = 'idle_mode'

    rospy.Subscriber( 'real_pose', Pose, self.update_robot_pose )
    self.pub_map_metadata = rospy.Publisher( 'map_metadata', MapMetaData, queue_size = 1, latch = True )
    self.pub_map = rospy.Publisher( 'map', OccupancyGrid, queue_size = 1, latch = True )
    self.pub_initial_pose = rospy.Publisher( 'initial_pose', Pose, queue_size = 1 )

    self.update_map()

  def add_margin( self, image ):
    height, width = image.shape[:2]
    horizontal_wall = np.zeros( ( self.wall_thick, width ), dtype = np.uint8 )
    vertical_wall = np.zeros( ( height + 2 * self.wall_thick, self.wall_thick ), dtype = np.uint8 )
    image = np.concatenate( (horizontal_wall, image, horizontal_wall), axis = 0 )
    image = np.concatenate( (vertical_wall, image, vertical_wall), axis = 1 )
    return image

  def open_map( self ):
    yamlfile = tkFileDialog.askopenfilename( title = 'Load Map', filetypes = [ ( 'YAML', ( '*.yaml' ) ) ] )
    if len( yamlfile ) == 0:
      return

    with open( yamlfile ) as fd:
      metadata = yaml.load( fd )

    if not os.path.isabs( metadata['image'] ):
      map_path = os.path.dirname( yamlfile )
      map_filename = os.path.basename( metadata['image'] )
      map_file = os.path.join( map_path, map_filename )
    else:
      map_file = metadata['image']

    self.resolution = metadata['resolution'] # [m/pix]
    self.robot_radio_pix = int( self.robot_radio / self.resolution )
    self.converter = CoordinateConverter( metadata['origin'][0], metadata['origin'][1], self.resolution )

    npimage = cv2.imread( map_file, cv2.IMREAD_GRAYSCALE )
    pilimage = PILImage.fromarray( npimage )
    self.width, self.height = pilimage.size
    bgimage = ImageTk.PhotoImage( pilimage )

    self.canvas.delete( 'robot' )
    self.canvas.delete( 'robot_direction' )
    self.canvas.delete( 'backgroundimg' )
    self.root.geometry( '%dx%d' % (self.width, self.height) )
    # keep a reference to the image to avoid the image being garbage collected
    self.canvas.pilimage = pilimage
    self.canvas.bgimage = bgimage
    self.canvas.config( width = self.width, height = self.height )
    self.canvas.create_image( 0, 0, anchor = NW, image = bgimage, tags = 'backgroundimg' )

    self.update_map()

  def click1( self, event ):
    self.statem[self.cstate].click1( event )

  def click1_motion( self, event ):
    self.statem[self.cstate].click1_motion( event )

  def click1_off( self, event ):
    self.statem[self.cstate].click1_off( event )
    if self.cstate == 'add_wall_mode' or self.cstate == 'delete_wall_mode':
      self.update_map()
    if self.cstate != 'idle_mode':
      self.cstate = 'idle_mode'
      self.canvas.config( cursor = 'left_ptr' )

  def key_pressed( self, event ):
    if event.keysym == 'w' and self.cstate != 'add_wall_mode':
      self.cstate = 'add_wall_mode'
      self.canvas.config( cursor = 'pencil' )
    elif event.keysym == 'w' and self.cstate == 'add_wall_mode':
      self.cstate = 'idle_mode'
      self.canvas.config( cursor = 'left_ptr' )
    elif event.keysym == 'd' and self.cstate != 'delete_wall_mode':
      self.cstate = 'delete_wall_mode'
      self.canvas.config( cursor = 'X_cursor' )
    elif event.keysym == 'd' and self.cstate == 'delete_wall_mode':
      self.cstate = 'idle_mode'
      self.canvas.config( cursor = 'left_ptr' )
    elif event.keysym == 'p' and self.cstate != 'set_robot_pose_mode':
      self.cstate = 'set_robot_pose_mode'
      self.canvas.config( cursor = 'hand1' )
    elif event.keysym == 'p' and self.cstate == 'set_robot_pose_mode':
      robot_pose = self.get_current_pose()
      self.send_initial_pose( robot_pose )
      self.cstate = 'idle_mode'
      self.canvas.config( cursor = 'left_ptr' )

  def get_current_pose( self ):
    coords = self.canvas.coords( 'robot' )
    radius = ( coords[2] - coords[0] )/2
    x = coords[0] + radius
    y = coords[1] + radius
    coords = self.canvas.coords( 'robot_direction' )
    yaw = np.arctan2( -(coords[3] - coords[1]), coords[2] - coords[0] )
    return x, y, yaw

  def send_initial_pose( self, robot_pose, metric = False ):
    if metric:
      x, y, yaw = robot_pose
    else:
      x, y = self.converter.pixel2metric( robot_pose[0], robot_pose[1] )
      yaw = robot_pose[2]
    quat = quaternion_from_euler( 0.0, 0.0, yaw )
    pix_pose = Pose( Point( x, y, 0.0 ), Quaternion( *quat ) )
    self.pub_initial_pose.publish( pix_pose )

  def update_robot_pose( self, pose ):
    if self.cstate != 'set_robot_pose_mode':
      x, y = self.converter.metric2pixel( pose.position.x, pose.position.y )
      roll, pitch, yaw = euler_from_quaternion( ( pose.orientation.x,
                                                  pose.orientation.y,
                                                  pose.orientation.z,
                                                  pose.orientation.w ) )
      if len( self.canvas.find_withtag( 'robot' ) ) == 0:
        self.canvas.create_oval( x-self.robot_radio_pix,
                                 y-self.robot_radio_pix,
                                 x+self.robot_radio_pix,
                                 y+self.robot_radio_pix,
                                 outline = 'red',
                                 fill = 'red',
                                 tags = 'robot' )
        x1 = int( x + self.robot_radio_pix * np.cos( yaw ) )
        y1 = int( y - self.robot_radio_pix * np.sin( yaw ) )
        self.canvas.create_line( x, y, x1, y1, fill = 'white', width = 2, tags = 'robot_direction' )
      else:
        coords = [x-self.robot_radio_pix, y-self.robot_radio_pix, x+self.robot_radio_pix, y+self.robot_radio_pix]
        self.canvas.coords( 'robot', *coords )
        x1 = int( x + self.robot_radio_pix * np.cos( yaw ) )
        y1 = int( y - self.robot_radio_pix * np.sin( yaw ) )
        coords = [x, y, x1, y1]
        self.canvas.coords( 'robot_direction', *coords )
      #rospy.loginfo( 'x: %d, y: %d, yaw: %f' % ( x, y, yaw ) )

  def update_map( self ):
    background_image = self.canvas.pilimage.copy()
    draw = PILImageDraw.Draw( background_image )
    item_list = self.canvas.find_all()
    for item in item_list:
      tag = self.canvas.gettags( item )[0]
      if tag.startswith( 'wall_' ):
        coords = self.canvas.coords( item )
        params = ['fill', 'width']
        opt = dict()
        for p in params:
          opt[p] = self.canvas.itemcget( item, p )
        draw.line( coords, fill = opt['fill'], width = int( float( opt['width'] ) ) )

    width, height = background_image.size

    map_quat = quaternion_from_euler( 0.0, 0.0, 0.0 )
    map_pose = Pose( Point( 0.0, height * self.resolution, 0.0 ), Quaternion( *map_quat ) )
    map_metadata = MapMetaData( rospy.Time.now(), self.resolution, width, height, map_pose )
    self.pub_map_metadata.publish( map_metadata )

    og_header = Header( 0, rospy.Time.now(), 'map_frame' )
    og_data = np.array( background_image )
    og_data = ( 100 - ( og_data / 255.0 ) * 100 ).astype( np.uint8 )
    og_data = og_data.reshape( height * width )
    occupancy_grid = OccupancyGrid( og_header, map_metadata, og_data.tolist() )
    self.pub_map.publish( occupancy_grid )

  def reset_state( self ):
    self.send_initial_pose( [float('inf'), float('inf'), 0.0], True )

  def mainloop( self ):
    self.root.mainloop()

  def sigint_handler( self, signum, frame ):
    rospy.loginfo( 'world_state_gui is shutting down' )
    self.root.quit()
    self.root.update()
    rospy.signal_shutdown( 'Signal received [%d]' % ( signum ) )

  def on_exit( self ):
    self.quit()


if __name__ == '__main__':
  rospy.init_node( 'world_state_gui', disable_signals = True )
  world_state_gui = WorldStateGUI()
  signal.signal( signal.SIGINT, world_state_gui.sigint_handler )
  signal.signal( signal.SIGTERM, world_state_gui.sigint_handler )
  world_state_gui.mainloop()


