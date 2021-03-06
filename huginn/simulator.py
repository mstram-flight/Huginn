"""
The huginn.simulator module contains classes that are used to run an aircraft
simulation
"""


import logging

from huginn import configuration
from huginn.aircraft import Aircraft
from huginn.fdm import FDM, FDMBuilder, TRIM_MODE_FULL


logger = logging.getLogger(__name__)


class SimulationError(Exception):
    """SimulationError raised when an error occurs during simulation"""
    pass


class SimulationBuilder(object):
    """The SimulationBuilder if a factory class that can be used to create a
    Simulator object"""
    def __init__(self, data_path):
        self.data_path = data_path
        self.dt = configuration.DT

        self.latitude = configuration.LATITUDE
        self.longitude = configuration.LONGITUDE
        self.altitude = configuration.ALTITUDE
        self.airspeed = configuration.AIRSPEED
        self.heading = configuration.HEADING

        self.trim_mode = TRIM_MODE_FULL
        self.start_paused = False

    def create_simulator(self):
        """Create the Simulator object"""
        fdm_builder = FDMBuilder(self.data_path)
        fdm_builder.dt = self.dt
        fdm_builder.latitude = self.latitude
        fdm_builder.longitude = self.longitude
        fdm_builder.altitude = self.altitude
        fdm_builder.airspeed = self.airspeed
        fdm_builder.heading = self.heading

        fdmexec = fdm_builder.create_fdm()

        aircraft = Aircraft(fdmexec)

        aircraft.start_engines()

        logger.debug("trimming the aircraft at mode %d", self.trim_mode)

        trim_result = aircraft.trim(self.trim_mode)
        if not trim_result:
            logger.warning("Failed to trim the aircraft")

            # reset the aircraft control because the trim operation might
            # have messed them up
            aircraft.controls.aileron = 0.0
            aircraft.controls.elevator = 0.0
            aircraft.controls.rudder = 0.0
            aircraft.controls.throttle = 0.0

        simulator = Simulator(fdmexec)
        simulator.trim_mode = self.trim_mode
        simulator.start_paused = self.start_paused

        result = simulator.step()

        if not result:
            logger.error("Failed to execute simulator run")
            return None

        if self.start_paused:
            simulator.pause()

        return simulator


class Simulator(object):
    """The Simulator class is used to perform the simulation of an aircraft"""

    def __init__(self, fdmexec):
        """Constructor for the Simulator object

        Arguments:
        fdmexec: A flight dynamics model
        """
        self.aircraft = Aircraft(fdmexec)
        self.fdmexec = fdmexec
        self.fdm = FDM(fdmexec)
        self.trim_mode = TRIM_MODE_FULL
        self._crashed = False
        self.start_paused = False

    @property
    def crashed(self):
        """Returns True if the aircraft has crashed"""
        return self._crashed

    @property
    def dt(self):
        """The simulation time step"""
        return self.fdmexec.GetDeltaT()

    @property
    def simulation_time(self):
        """The current simulation time"""
        return self.fdmexec.GetSimTime()

    def pause(self):
        """Pause the simulator"""
        self.fdmexec.Hold()

    def resume(self):
        """Resume the simulation"""
        if self.crashed:
            logger.debug("Not resuming simulation because the aircraft has "
                         "crashed")
            return

        if self.fdmexec.IntegrationSuspended():
            self.fdmexec.ResumeIntegration()

        self.fdmexec.Resume()

    def is_paused(self):
        """Check if the simulator is paused"""
        return self.fdmexec.Holding()

    def reset(self):
        """Reset the simulation"""
        logger.debug("Reseting the aircraft")
        self._crashed = False

        self.pause()

        self.aircraft.controls.aileron = 0.0
        self.aircraft.controls.elevator = 0.0
        self.aircraft.controls.rudder = 0.0
        self.aircraft.controls.throttle = 0.0

        self.fdmexec.ResetToInitialConditions(0)

        if not self.fdmexec.RunIC():
            logger.error("Failed to run initial condition")
            return False

        logger.debug("starting the aircraft's engines")
        self.aircraft.start_engines()

        trim_result = self.aircraft.trim(self.trim_mode)
        if not trim_result:
            logger.warning("Failed to trim the aircraft")

            # reset the controls because the trim operation might have messed
            # them up
            self.aircraft.controls.aileron = 0.0
            self.aircraft.controls.elevator = 0.0
            self.aircraft.controls.rudder = 0.0
            self.aircraft.controls.throttle = 0.0

        if not self.step():
            logger.error("Failed to execute initial run")
            return False

        logger.debug("Engine thrust after simulation reset %f",
                     self.aircraft.engine.thrust)

        if not self.start_paused:
            self.resume()

        return True

    def step(self):
        """Run the simulation one time"""
        if not self.crashed and self.fdm.position.altitude < 0.0:
            logger.debug("Aircraft has crashed. Pausing simulator")
            self.pause()
            self._crashed = True
            return True

        if self.crashed:
            logger.debug("Not executing simulation step because aircraft has "
                         "crashed")
            return True

        was_paused = self.is_paused()

        if was_paused:
            self.resume()

        try:
            self.fdmexec.ProcessMessage()
            self.fdmexec.CheckIncrementalHold()
            run_result = self.fdmexec.Run()
        except:
            raise SimulationError()

        if run_result:
            if was_paused:
                self.pause()

            return True
        else:
            if was_paused:
                self.pause()

            logger.error("The simulator has failed to run")
            return False

    def run_for(self, time_to_run):
        """Run the simulation for the given time in seconds

        Arguments:
        time_to_run: the time in seconds that the simulator will run
        """
        if time_to_run < 0.0:
            logger.error("Invalid simulator run time length %f",
                         time_to_run)

            return False

        start_time = self.fdmexec.GetSimTime()
        end_time = start_time + time_to_run

        while self.fdmexec.GetSimTime() <= end_time:
            result = self.step()

            if not result:
                return False

        return True

    def run(self):
        """Run the simulation"""
        if not self.fdmexec.Holding():
            result = self.step()

            return result

        return True

    def set_aircraft_controls(self, aileron, elevator, rudder, throttle):
        """Update the aircraft controls"""
        self.aircraft.controls.aileron = aileron
        self.aircraft.controls.elevator = elevator
        self.aircraft.controls.rudder = rudder
        self.aircraft.controls.throttle = throttle

    def print_simulator_state(self):
        """Show the current state of the simulation"""
        print("Simulation state")
        print("================")
        print("Time: %f seconds" % self.simulation_time)
        print("DT: %f seconds" % self.dt)
        print("Running: %s" % (not self.is_paused()))
        print("")
