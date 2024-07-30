
#20 -> car width
#72 -> track width without lines
#80 -> track width
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Joy
import math
from synapse_msgs.msg import EdgeVectors
from synapse_msgs.msg import TrafficStatus
from sensor_msgs.msg import LaserScan
#OURS
import numpy as np
from geometry_msgs.msg import PoseWithCovarianceStamped

QOS_PROFILE_DEFAULT = 10
PI = math.pi
LEFT_TURN = +1.0
RIGHT_TURN = -1.0
TURN_MIN = 0.0
TURN_MAX = 1.0
SPEED_MIN = 0.0
SPEED_MAX = 1.4
SPEED_25_PERCENT = SPEED_MAX / 4
SPEED_50_PERCENT = SPEED_25_PERCENT * 2
SPEED_75_PERCENT = SPEED_25_PERCENT * 3
THRESHOLD_OBSTACLE_VERTICAL = 0.3
THRESHOLD_OBSTACLE_HORIZONTAL = 0.25
THRESHOLD_RAMP_MIN = 0.7
THRESHOLD_RAMP_MAX = 1.2
#Min - 0.6179950833320618 and Max - 0.9302666783332825
#Min - 0.4310002624988556 and Max - 1.9826102256774902
class LineFollower(Node):
    """ Initializes line follower node with the required publishers and subscriptions.
        Returns:
            None
    """
    def __init__(self):
        super().__init__('line_follower')
        self.status = [0, 0, 0]
        self.prevSpeed, self.prevTurn = 0.75, 0
        self.min, self.max = 10, 0
        self.obs = 0
        self.speed, self.turn = 0.0, 0.0

        self.subscription_vectors = self.create_subscription(
            EdgeVectors,
            '/edge_vectors',
            self.edge_vectors_callback,
            QOS_PROFILE_DEFAULT)
        # Publisher for joy (for moving the rover in manual mode).
        self.publisher_joy = self.create_publisher(
            Joy,
            '/cerebri/in/joy',
            QOS_PROFILE_DEFAULT)
        # Subscription for traffic status.
        self.subscription_traffic = self.create_subscription(
            TrafficStatus,
            '/traffic_status',
            self.traffic_status_callback,
            QOS_PROFILE_DEFAULT)
        # Subscription for LIDAR data.
        self.subscription_lidar = self.create_subscription(
            LaserScan,
            '/scan',
            self.lidar_callback,
            QOS_PROFILE_DEFAULT)
        self.traffic_status = TrafficStatus()
        self.obstacle_detected = False
        self.ramp_detected = False
        self.LoopSetter()
    """ Operates the rover in manual mode by publishing on /cerebri/in/joy.
        Args:
            speed: the speed of the car in float. Range = [-1.0, +1.0];
                Direction: forward for positive, reverse for negative.
            turn: steer value of the car in float. Range = [-1.0, +1.0];
                Direction: left turn for positive, right turn for negative.
        Returns:
            None
    """
    def rover_move_manual_mode(self, speed, turn):
        msg = Joy()
        msg.buttons = [1, 0, 0, 0, 0, 0, 0, 1]
        msg.axes = [0.0, speed, 0.0, turn]
        self.publisher_joy.publish(msg)

    """ Analyzes edge vectors received from /edge_vectors to achieve line follower application.
        It checks for existence of ramps & obstacles on the track through instance members.
            These instance members are updated by the lidar_callback using LIDAR data.
        The speed and turn are calculated to move the rover using rover_move_manual_mode.
        Args:
            message: "~/cognipilot/cranium/src/synapse_msgs/msg/EdgeVectors.msg"
        Returns:
            None
    """
    def edge_vectors_callback(self, message):
        speed = SPEED_MAX
        turn = TURN_MIN
        vectors = message
        half_width = vectors.image_width / 2
        
        p_turn = 0.0
        kP_base = 0.65
        kD_base = 0.35
        
        # NOTE: participants may improve algorithm for line follower.
        if (vectors.vector_count == 0):  # none.
            speed = SPEED_25_PERCENT
            turn = self.prevTurn*0.95
            #print("ZERO (0) Vectors formed")
        if (vectors.vector_count == 1):  # curve.
            # Calculate the magnitude of the x-component of the vector.
            deviation = vectors.vector_1[1].x - vectors.vector_1[0].x
            p_turn = deviation * 2 / vectors.image_width
            speed = SPEED_75_PERCENT * (np.abs(math.cos(turn))**(1/2))
            #speed = speed * (np.abs(math.cos(turn))**(1/2))
            #print("ONE (1) Vector formed")

        if (vectors.vector_count == 2):  # straight.
            # Calculate the middle point of the x-components of the vectors.
            middle_x_left = (vectors.vector_1[0].x + vectors.vector_1[1].x) / 2
            middle_x_right = (vectors.vector_2[0].x + vectors.vector_2[1].x) / 2
            middle_x = (middle_x_left + middle_x_right) / 2
            deviation = half_width - middle_x
            p_turn = deviation * 2 / half_width
            #speed = speed * (np.abs(math.cos(turn))**(1/4))
            speed = SPEED_MAX
            #print("TWO (2) Vectors formed.")
        
        deviation_magnitude = abs(p_turn)
        kP = kP_base * (1 + deviation_magnitude)
        kD = kD_base * (1 + deviation_magnitude)
        derivative_turn = (turn - self.prevTurn)

        turn = kP * p_turn + kD * derivative_turn
            
        if (self.traffic_status.stop_sign is True):
            speed = SPEED_MIN
            #print("stop sign detected")
        if self.ramp_detected is True:
            # TODO: participants need to decide action on detection of ramp/bridge.
            speed = 0.65
            '''change it to reduce speed close to the ramp'''
            print("ramp/bridge detected")
        if self.obstacle_detected is True:
            # TODO: participants need to decide action on detection of obstacle.
            speed = SPEED_50_PERCENT*0.7
            turn = -0.95*self.obs + turn*0.05
            print("obstacle detected") 
        #While goind down/ after ramp to avoid bouncing of buggs
        if self.prevSpeed < 0.75 and speed > 0.64 and self.obstacle_detected is False:
            speed = 0.995*self.prevSpeed + 0.005*speed
        
        self.speed = speed
        self.turn = turn
    """ Updates instance member with traffic status message received from /traffic_status.
        Args:
            message: "~/cognipilot/cranium/src/synapse_msgs/msg/TrafficStatus.msg"
        Returns:
            None
    """
    def traffic_status_callback(self, message):
        self.traffic_status = message
    """ Analyzes LIDAR data received from /scan topic for detecting ramps/bridges & obstacles.
        Args:
            message: "docs.ros.org/en/melodic/api/sensor_msgs/html/msg/LaserScan.html"
        Returns:
            None
        range_1=message.ranges
        #range_difference =  [range_1[i+1] - range_1[i] for i in range(len(range_1) - 1)]
        
        #Can also be for obsracles -> need to differentiate between them smhow
        for distance in range_1:
            if distance < 2:
                self.ramp_detected = True
                break
    """
    def lidar_callback(self, message):
        # TODO: participants need to implement logic for detection of ramps and obstacles.
        shield_vertical = 4
        shield_horizontal = 1
        theta = math.atan(shield_vertical / shield_horizontal)  #75.96
        self.ramp_detected = False
        angles = []
        # Get the middle half of the ranges array returned by the LIDAR.
        length = float(len(message.ranges))
        
        #backRanges = message.ranges[0:int(length / 4), int(3 * length / 4) : int(length)]
        ranges = message.ranges[int(length / 4): int(3 * length / 4)]
        # Separate the ranges into the part in the front and the part on the sides.
        length = float(len(ranges))
        front_ranges = ranges[int(length * theta / PI): int(length * (PI - theta) / PI)]
        side_ranges_right = ranges[0: int(length * theta / PI)]
        side_ranges_left = ranges[int(length * (PI - theta) / PI):]
        
        # process front ranges.
        angle1 = theta - PI / 2
        for i in range(len(front_ranges)):
            #
            if (front_ranges[i] < THRESHOLD_OBSTACLE_VERTICAL):
                #print("FRONT",min(front_ranges))
                self.obstacle_detected = True
                angleAvoidance = angle1
                angleSafe = np.arctan(0.1/front_ranges[i])
                angle1 = angleAvoidance + np.abs(angleSafe)*np.sign(angleAvoidance) 
                '''+ np.abs(angleSafe)'''
                self.obs = angle1
                angles.append(angle1)
                break
            angle1 += message.angle_increment

        # angle12 = theta - PI / 2
        # front_ranges.reverse()
        # for i in range(len(front_ranges)):
        #     #
        #     if (front_ranges[i] < THRESHOLD_OBSTACLE_VERTICAL):
        #         #print("FRONT",min(front_ranges))
        #         self.obstacle_detected = True
        #         angleAvoidance = angle12
        #         angleSafe = np.arctan(1/front_ranges[i])
        #         angle1 = angleAvoidance + np.abs(angleSafe)*np.sign(angleAvoidance) 
        #         '''+ np.abs(angleSafe)'''
        #         self.obs = angle12
        #         angles.append(angle12)
        #         break
        #     angle12 += message.angle_increment

        # process side Left
        side_ranges_left.reverse()
        angle2 = 0.0
        for i in range(len(side_ranges_left)):
            #
            if (side_ranges_left[i] < THRESHOLD_OBSTACLE_HORIZONTAL):
                #print("LEFT",min(side_ranges_left))
                self.obstacle_detected = True
                angleAvoidance = angle2
                angleSafe = np.arctan(0.1/side_ranges_left[i])
                angle2 = angleAvoidance + np.abs(angleSafe)*np.sign(angleAvoidance)
                self.obs = 1*angle2
                angles.append(1*angle2)
                break
            angle2 += message.angle_increment
        # process side Right
        angle3 = 0.0
        for i in range(len(side_ranges_right)):
            
            if (side_ranges_right[i] < THRESHOLD_OBSTACLE_HORIZONTAL):
                #print("RIGHT",min(side_ranges_right))
                self.obstacle_detected = True
                angleAvoidance = angle3
                angleSafe = np.arctan(0.1/side_ranges_right[i])
                angle3 = angleAvoidance + np.abs(angleSafe)*np.sign(angleAvoidance)
                self.obs = angle3
                angles.append(angle3)
                break
            angle3 += message.angle_increment
        if len(angles) == 3:
            self.obs = np.dot(angles, [0.4,0.3,0.3])
            return
        if len(angles) == 2 and angles[0] == angle1:
            self.obs = np.dot(angles, [0.7,0.3])
            return
        if len(angles) == 2:
            self.obs = np.dot(angles, [0.5,0.5])
            return
        if len(angles) == 1:
            return
        
        self.obstacle_detected = False
        # RAMP
        l = len(front_ranges)
        new_front_ranges = front_ranges[int(l/6):int(5*l/6)]
        for i in range(len(new_front_ranges)):
            if (new_front_ranges[i] < THRESHOLD_RAMP_MAX and new_front_ranges[i] > THRESHOLD_RAMP_MIN):
                self.ramp_detected = True
                return
            
        self.ramp_detected = False
        
    def pose_callback(self, Message):
        self.status = [Message.pose.pose.position.x, Message.pose.pose.position.y, 0]
        x = Message.pose.pose.orientation.x
        y = Message.pose.pose.orientation.y
        z = Message.pose.pose.orientation.z
        w = Message.pose.pose.orientation.w
        t3 = +2.0 * (w * z + x * y)
        t4 = +1.0 - 2.0 * (y * y + z * z)
        yaw_z = np.arctan2(t3, t4)
        self.status[2] = yaw_z
        
    def MainLoop(self):
        self.prevSpeed = self.speed
        self.prevTurn = self.turn
        self.rover_move_manual_mode(self.speed, self.turn)

    def LoopSetter(self):
        """
        This function is called when the node is started. It runs the main loop at a fixed rate.
        """
        
        timerPeriod = 1/30
        
        try:
            self.timer = self.create_timer(timerPeriod, self.MainLoop)

        except KeyboardInterrupt:
            print("ROS Interrupt Exception")
            
            exit(1)

def main(args=None):
    rclpy.init(args=args)
    line_follower = LineFollower()
    rclpy.spin(line_follower)
    line_follower.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
