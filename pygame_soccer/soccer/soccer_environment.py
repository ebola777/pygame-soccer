# Native modules
import random

# Third-party modules
import numpy as np

# User-defined modules
import pygame_soccer.renderer.pygame_renderer as pygame_renderer
import pygame_soccer.rl.environment as environment
import pygame_soccer.soccer.soccer_renderer as soccer_renderer
import pygame_soccer.util.file_util as file_util


class SoccerEnvironment(environment.Environment):
  """The soccer environment.
  """
  # Team name list
  team_names = [
      'PLAYER',
      'COMPUTER',
  ]

  # Computer mode list
  modes = [
      'DEFENSIVE',
      'OFFENSIVE',
  ]

  # Action list
  actions = [
      'MOVE_RIGHT',
      'MOVE_UP',
      'MOVE_LEFT',
      'MOVE_DOWN',
      'STAND',
  ]

  # Environment options
  options = None

  # State
  state = None

  # Map data
  map_data = None

  # Renderer
  renderer = None
  renderer_loaded = False

  def __init__(self, env_options=None, renderer_options=None):
    # Save or create the environment options
    self.options = env_options or SoccerEnvironmentOptions()
    # Load the map data
    self.map_data = SoccerMapData(self.options.map_path)
    # Initialize the state
    self.state = SoccerState(self, self.options, self.map_data)
    # Initialize the renderer
    self.renderer = soccer_renderer.SoccerRenderer(
        self.options.map_path, self, renderer_options)

  def reset(self):
    self.state.reset()
    return SoccerObservation(self.state, None, 0.0, None)

  def take_action(self, action):
    # Get the action wrapped in a list
    action = self._get_wrapped_action(action)
    # Get the intended positions
    intended_pos = self._get_intended_pos(action)
    # Update the agent positions
    self._update_agent_pos(intended_pos)
    # Increase the time step
    self.state.increase_time_step()
    # Get the reward
    reward = self._get_reward()
    # Return the observation, the original state is not returned to increase
    # the speed, otherwise deep copying must be used before changing the
    # position.
    return SoccerObservation(None, action, reward, self.state)

  def render(self):
    # Lazy load the renderer
    if not self.renderer_loaded:
      self.renderer.load()
      self.renderer_loaded = True
    # Render
    self.renderer.render()

  def get_agent_index(self, team_name, team_agent_index):
    # Map the team name to the group index
    if team_name == 'PLAYER':
      group_index = 0
    elif team_name == 'COMPUTER':
      group_index = 1
    else:
      raise KeyError('Unknown team name {}'.format(team_name))
    # Calculate the agent index
    return self.options.team_size * group_index + team_agent_index

  def _get_wrapped_action(self, action):
    # Wrap the action in a list if it's in the single-agent environment
    if self.options.team_size <= 1 and not isinstance(action, list):
      action = [action]
    # Check the size of the action should be the same as the team size
    if len(action) != self.options.team_size:
      raise ValueError('"action" should have the same size as the team size')
    return action

  def _get_intended_pos(self, action):
    # Build a dict of the agent index to the intended moved position
    intended_pos = {}
    for team_name in self.team_names:
      for team_agent_index in range(self.options.team_size):
        agent_index = self.get_agent_index(team_name, team_agent_index)
        pos = self.state.get_agent_pos(agent_index)
        if team_name == 'PLAYER':
          agent_action = action[team_agent_index]
        elif team_name == 'COMPUTER':
          agent_action = self._get_computer_action(team_agent_index)
        else:
          raise KeyError('Unknown team name {}'.format(team_name))
        # Save the action taken by the agent
        self.state.set_agent_action(agent_index, agent_action)
        # Get the moved position
        moved_pos = self.get_moved_pos(pos, agent_action)
        # Use the moved position if it's in the walkable area
        if moved_pos in self.map_data.walkable:
          intended_pos[agent_index] = moved_pos
        else:
          intended_pos[agent_index] = pos
    return intended_pos

  def _update_agent_pos(self, intended_pos):
    # Detect the overlapping positions and switch the ball
    detecting_overlap = True
    has_switched = False
    while detecting_overlap:
      # Get the overlapping position to agent index mapping
      overlapping_pos_to_agent = self._get_overlapping_pos_to_agent(
          intended_pos)
      # Update the positions
      detecting_overlap = False
      for (_, agent_index_list) in overlapping_pos_to_agent.items():
        if len(agent_index_list) > 1:
          # Update the ball possession only once
          if not has_switched:
            switch = self._update_ball_possession(agent_index_list)
            has_switched = has_switched or switch
          # Use the old positions
          for agent_index in agent_index_list:
            intended_pos[agent_index] = self.state.get_agent_pos(agent_index)
          # Indicate the process should continue
          detecting_overlap = True
    # Update the non-overlapping positions
    for (agent_index, pos) in intended_pos.items():
      self.state.set_agent_pos(agent_index, pos)

  def _update_ball_possession(self, agent_index_list):
    # Get the ball possessions of the agents
    has_ball_agent_index = None
    no_ball_agent_list = []
    for agent_index in agent_index_list:
      has_ball = self.state.get_agent_ball(agent_index)
      if has_ball:
        has_ball_agent_index = agent_index
      else:
        no_ball_agent_list.append(agent_index)
    # Only switch the ball possession when one agent has the ball in the list
    if not has_ball_agent_index is None:
      # Randomly switch the ball
      switch_agent_index = random.choice(no_ball_agent_list)
      self.state.switch_ball(has_ball_agent_index, switch_agent_index)
      # Indicate the switching has occurred
      return True
    # Indicate no switch
    return False

  def _get_computer_action(self, computer_agent_index):
    # Get the computer agent info
    agent_index = self.get_agent_index('COMPUTER', computer_agent_index)
    computer_ball = self.state.get_agent_ball(agent_index)
    computer_mode = self.state.get_agent_mode(agent_index)
    # Get the position of the nearest player
    nearest_player_index = self._get_nearest_player_index(computer_agent_index)
    nearest_player_pos = self.state.get_agent_pos(nearest_player_index)
    # Get the position of the defensive target
    defensive_target_agent_index = self._get_defensive_agent_index(
        computer_agent_index)
    defensive_target_agent_pos = self.state.get_agent_pos(
        defensive_target_agent_index)
    # Calculate the target position and the strategic mode
    computer_pos = self.state.get_agent_pos(agent_index)
    if computer_mode == 'DEFENSIVE':
      if computer_ball:
        target_pos = nearest_player_pos
        strategic_mode = 'AVOID'
      else:
        # Calculate the distance from the agent
        goals = self.map_data.goals['PLAYER']
        distances = [self.get_pos_distance(goal_pos, defensive_target_agent_pos)
                     for goal_pos in goals]
        # Select the minimum distance
        min_distance_index = np.argmin(distances)
        target_pos = goals[min_distance_index]
        strategic_mode = 'APPROACH'
    elif computer_mode == 'OFFENSIVE':
      if computer_ball:
        # Calculate the distance from the player
        goals = self.map_data.goals['COMPUTER']
        distances = [self.get_pos_distance(goal_pos, nearest_player_pos)
                     for goal_pos in goals]
        # Select the maximum distance
        min_distance_index = np.argmax(distances)
        target_pos = goals[min_distance_index]
        strategic_mode = 'APPROACH'
      else:
        target_pos = defensive_target_agent_pos
        strategic_mode = 'INTERCEPT'
    else:
      raise KeyError('Unknown computer agent mode {}'.format(computer_mode))
    # Get the strategic action
    action = self._get_strategic_action(
        computer_pos, target_pos, strategic_mode)
    return action

  def _get_nearest_player_index(self, computer_agent_index):
    # Get the computer agent position
    agent_index = self.get_agent_index('COMPUTER', computer_agent_index)
    computer_pos = self.state.get_agent_pos(agent_index)
    # Find the nearest player position
    nearest_agent_index = None
    nearest_dist = None
    for player_agent_index in range(self.options.team_size):
      agent_index = self.get_agent_index('PLAYER', player_agent_index)
      player_pos = self.state.get_agent_pos(agent_index)
      # Calculate the distance
      dist = self.get_pos_distance(computer_pos, player_pos)
      if nearest_dist is None or dist < nearest_dist:
        nearest_agent_index = agent_index
        nearest_dist = dist
    return nearest_agent_index

  def _get_defensive_agent_index(self, computer_agent_index):
    # Get the ball possession status
    ball_possession = self.state.get_ball_possession()
    has_ball_agent_index = ball_possession['agent_index']
    has_ball_team_name = ball_possession['team_name']
    if has_ball_team_name == 'PLAYER':
      # Defend the player who possesses the ball
      return has_ball_agent_index
    else:
      # Defend the nearest player
      return self._get_nearest_player_index(computer_agent_index)

  def _get_strategic_action(self, source_pos, target_pos, mode):
    # Calculate the original Euclidean distance
    orig_dist = self.get_pos_distance(source_pos, target_pos)
    # Find the best action
    best_action = random.choice(self.actions)
    best_dist = orig_dist
    # Shuffle the actions
    shuffled_actions = random.sample(self.actions, len(self.actions))
    # Find the best action
    for action in shuffled_actions:
      # Get the moved position after doing the action
      moved_pos = self.get_moved_pos(source_pos, action)
      # Check whether the moved position is walkable
      if not moved_pos in self.map_data.walkable:
        continue
      # Calculate the new Euclidean distance
      moved_dist = self.get_pos_distance(moved_pos, target_pos)
      if mode == 'APPROACH':
        if moved_dist < best_dist:
          best_action = action
          best_dist = moved_dist
      elif mode == 'AVOID':
        if moved_dist > best_dist:
          best_action = action
          best_dist = moved_dist
      elif mode == 'INTERCEPT':
        if moved_dist < best_dist and moved_dist >= 1.0:
          best_action = action
          best_dist = moved_dist
      else:
        raise KeyError('Unknown mode {}'.format(mode))
    return best_action

  def _get_overlapping_pos_to_agent(self, intended_pos):
    overlapping_pos_to_agent = {}
    for (agent_index, pos) in intended_pos.items():
      # Use the old position if the new position is not walkable
      if not pos in self.map_data.walkable:
        pos = self.state.get_agent_pos(agent_index)
      # Use the tuple as the key
      pos_tuple = tuple(pos)
      if pos_tuple in overlapping_pos_to_agent:
        overlapping_pos_to_agent[pos_tuple].append(agent_index)
      else:
        overlapping_pos_to_agent[pos_tuple] = [agent_index]
    return overlapping_pos_to_agent

  def _get_reward(self):
    if self.state.is_team_win('PLAYER'):
      return 1.0
    elif self.state.is_team_win('COMPUTER'):
      return -1.0
    else:
      return 0.0

  @staticmethod
  def get_moved_pos(pos, action):
    # Copy the position
    pos = list(pos)
    # Move to the 4-direction grid
    if action == 'MOVE_RIGHT':
      pos[0] += 1
    elif action == 'MOVE_UP':
      pos[1] -= 1
    elif action == 'MOVE_LEFT':
      pos[0] -= 1
    elif action == 'MOVE_DOWN':
      pos[1] += 1
    elif action == 'STAND':
      pass
    else:
      raise KeyError('Unknown action {}'.format(action))
    return pos

  @staticmethod
  def get_pos_distance(pos1, pos2):
    vec = [pos2[0] - pos1[0], pos2[1] - pos1[1]]
    return np.linalg.norm(vec)


class SoccerEnvironmentLegacy(SoccerEnvironment):
  """The soccer environment using legacy methods.
  """
  pass


class SoccerEnvironmentOptions(object):
  """The options for the soccer environment.
  """
  # Resource names
  map_resource_name = 'pygame_soccer/data/map/soccer.tmx'

  # Map path
  map_path = None

  # Team size
  team_size = 1

  def __init__(self, map_path=None, team_size=1):
    # Save the map path or use the internal resource
    if map_path:
      self.map_path = map_path
    else:
      self.map_path = file_util.get_resource_path(self.map_resource_name)
    # Check the team size
    if not (team_size >= 1 and team_size <= 2):
      raise ValueError('"team_size" should be either 1 or 2')
    # Save the team size
    self.team_size = team_size

  def get_agent_size(self):
    return 2 * self.team_size

  def __repr__(self):
    return 'Team size: {}'.format(self.team_size)


class SoccerMapData(object):
  """The soccer map data as the geographical info.
  """
  # Tile positions
  spawn = []
  goals = []
  walkable = []

  def __init__(self, map_path):
    # Create a tile data and load
    tiled_data = pygame_renderer.TiledData(map_path)
    tiled_data.load()
    # Get the background tile positions
    tile_pos = tiled_data.get_tile_positions()
    # Build the tile positions
    self.spawn = tile_pos['spawn_area']
    self.goals = tile_pos['goal']
    self.walkable = tile_pos['ground']['WALKABLE']


class SoccerObservation(object):
  """The observation as a response by the environment.
  """
  state = None
  action = None
  reward = 0.0
  next_state = None

  def __init__(self, state, action, reward, next_state):
    self.state = state
    self.action = action
    self.reward = reward
    self.next_state = next_state

  def __repr__(self):
    return 'State:\n{}\nAction: {}\nReward: {}\nNext state:\n{}'.format(
        self.state, self.action, self.reward, self.next_state)


class SoccerState(object):
  """The internal soccer state.
  """
  # Agent statuses as a list
  # * pos: Positions
  # * ball: Possession of the ball
  # * mode: Mode for the computer agent
  # * action: Last taken action for the computer agent
  agent_list = []

  # Time step
  time_step = 0

  # Soccer environment
  env = None

  # Soccer environment options
  env_options = None

  # Map data
  map_data = None

  def __init__(self, env, env_options, map_data):
    self.env = env
    self.env_options = env_options
    self.map_data = map_data
    self.reset()

  def reset(self):
    # Initialize the agent list
    self.agent_list = [{} for _ in range(self.env_options.get_agent_size())]
    for agent_index in range(self.env_options.get_agent_size()):
      self.set_agent_pos(agent_index, None)
      self.set_agent_ball(agent_index, False)
      self.set_agent_mode(agent_index, None)
      self.set_agent_action(agent_index, None)
    # Randomize the agent statuses
    self.randomize()
    # Initialize the time step
    self.time_step = 0

  def randomize(self):
    # Choose a random agent in a random team to possess the ball
    team_has_ball = random.choice(self.env.team_names)
    team_agent_has_ball = random.randrange(self.env_options.team_size)
    # Set the properties for each team and each agent
    for team_name in self.env.team_names:
      for team_agent_index in range(self.env_options.team_size):
        # Get the agent index
        agent_index = self.env.get_agent_index(team_name, team_agent_index)
        # Randomize the agent positions
        found_pos = False
        while not found_pos:
          agent_pos = random.choice(self.map_data.spawn[team_name])
          if not self.get_pos_status(agent_pos):
            self.set_agent_pos(agent_index, agent_pos)
            found_pos = True
        # Randomize the possession of the ball
        set_ball = (team_name == team_has_ball
                    and team_agent_index == team_agent_has_ball)
        if set_ball:
          self.set_agent_ball(agent_index, True)
        else:
          self.set_agent_ball(agent_index, False)
        # Randomize the agent mode
        if team_name == 'COMPUTER':
          computer_mode = random.choice(self.env.modes)
          self.set_agent_mode(agent_index, computer_mode)
        else:
          self.set_agent_mode(agent_index, None)
        # Reset the action
        self.set_agent_action(agent_index, self.env.actions[-1])

  def is_terminal(self):
    # When the time step exceeds 100
    if self.time_step >= 100:
      return True
    # When one of the agent reaches the goal
    for agent_index in range(self.env_options.get_agent_size()):
      if self.is_agent_win(agent_index):
        return True
    # Otherwise, the state isn't terminal
    return False

  def is_team_win(self, team_name):
    for team_agent_index in range(self.env_options.team_size):
      agent_index = self.env.get_agent_index(team_name, team_agent_index)
      if self.is_agent_win(agent_index):
        return True
    return False

  def is_agent_win(self, agent_index):
    # Get the agent statuses
    agent_pos = self.get_agent_pos(agent_index)
    has_ball = self.get_agent_ball(agent_index)
    # Agent cannot win if he doesn't possess the ball
    if not has_ball:
      return False
    # Get the team name
    team_name = self.get_team_name(agent_index)
    # Check whether the position is in the goal area
    return agent_pos in self.map_data.goals[team_name]

  def get_agent_pos(self, agent_index):
    return self.agent_list[agent_index]['pos']

  def set_agent_pos(self, agent_index, pos):
    self.agent_list[agent_index]['pos'] = pos

  def get_agent_ball(self, agent_index):
    return self.agent_list[agent_index]['ball']

  def set_agent_ball(self, agent_index, has_ball):
    self.agent_list[agent_index]['ball'] = has_ball

  def get_agent_mode(self, agent_index):
    return self.agent_list[agent_index]['mode']

  def set_agent_mode(self, agent_index, mode):
    self.agent_list[agent_index]['mode'] = mode

  def get_agent_action(self, agent_index):
    return self.agent_list[agent_index]['action']

  def set_agent_action(self, agent_index, action):
    self.agent_list[agent_index]['action'] = action

  def get_team_name(self, agent_index):
    if agent_index < self.env_options.team_size:
      return 'PLAYER'
    else:
      return 'COMPUTER'

  def switch_ball(self, agent_index, other_agent_index):
    agent_ball = self.get_agent_ball(agent_index)
    self.set_agent_ball(agent_index, not agent_ball)
    self.set_agent_ball(other_agent_index, agent_ball)

  def get_pos_status(self, pos):
    for team_name in self.env.team_names:
      for team_agent_index in range(self.env_options.team_size):
        agent_index = self.env.get_agent_index(team_name, team_agent_index)
        if pos == self.get_agent_pos(agent_index):
          return {
              'team_name': team_name,
              'team_agent_index': team_agent_index,
              'agent_index': agent_index,
          }
    return None

  def get_ball_possession(self):
    for team_name in self.env.team_names:
      for team_agent_index in range(self.env_options.team_size):
        agent_index = self.env.get_agent_index(team_name, team_agent_index)
        if self.get_agent_ball(agent_index):
          return {
              'team_name': team_name,
              'team_agent_index': team_agent_index,
              'agent_index': agent_index,
          }
    return None

  def increase_time_step(self):
    self.time_step += 1

  def __repr__(self):
    message = ''
    # The agent positions, mode, and last taken action
    for team_index in range(len(self.env.team_names)):
      team_name = self.env.team_names[team_index]
      if team_index > 0:
        message += '\n'
      message += 'Team {}:'.format(team_name)
      for team_agent_index in range(self.env_options.team_size):
        # Get the agent index
        agent_index = self.env.get_agent_index(team_name, team_agent_index)
        # Get the position
        agent_pos = self.get_agent_pos(agent_index)
        # Get the mode
        agent_mode = self.get_agent_mode(agent_index)
        # Get the last taken action
        agent_action = self.get_agent_action(agent_index)
        message += '\nAgent {}:'.format(team_agent_index + 1)
        message += ' Position: {}'.format(agent_pos)
        if agent_mode:
          message += ', Mode: {}'.format(agent_mode)
        if agent_action:
          message += ', Action: {}'.format(agent_action)
    # The possession of the ball
    ball_possession = self.get_ball_possession()
    team_name = ball_possession['team_name']
    team_agent_index = ball_possession['team_agent_index']
    message += '\nBall possession: In team {} with agent {}'.format(
        team_name, team_agent_index + 1)
    # The time step
    message += '\nTime step: {}'.format(self.time_step)
    return message

  def __eq__(self, other):
    if not isinstance(other, SoccerState):
      return False
    return (self.agent_list == other.agent_list
            and self.time_step == other.time_step)

  def __hash__(self):
    hash_list = []
    for agent_index in range(self.env_options.get_agent_size()):
      hash_list.extend(self.get_agent_pos(agent_index))
      hash_list.append(self.get_agent_ball(agent_index))
      hash_list.append(self.get_agent_mode(agent_index))
      hash_list.append(self.get_agent_action(agent_index))
    hash_list.append(self.time_step)
    return hash(tuple(hash_list))
