# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the “License”);
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an “AS IS” BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========

import asyncio
import logging
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Assuming InferenceThread and SharedMemory are defined elsewhere
from oasis.inference.inference_thread import InferenceThread

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('inference.log'),
              logging.StreamHandler()])
logger = logging.getLogger(__name__)


@dataclass
class SharedMemory:
    """Using dataclass for optimized memory usage and access efficiency"""
    Message_ID: Optional[str] = None
    Message: Optional[str] = None
    Agent_ID: Optional[int] = None
    Response: Optional[str] = None
    Done: bool = False
    Busy: bool = False
    Working: bool = False
    last_active: float = field(
        default_factory=time.time)  # Record last active time


class PortManager:
    """Class to manage port allocations"""

    def __init__(self, port_ranges: Dict[Tuple[int, int], range]):
        self.port_ranges = port_ranges
        self.agent_to_ports: Dict[int, List[int]] = defaultdict(list)
        self._initialize_mappings()

    def _initialize_mappings(self):
        """Initialize agent_id to port mappings"""
        port_ranges_dict = {
            (entry["range"]["start"], entry["range"]["end"]): entry["ports"]
            for entry in self.port_ranges
        }
        for (start_id, end_id), ports in port_ranges_dict.items():
            for agent_id in range(start_id, end_id + 1):
                self.agent_to_ports[agent_id].extend(ports)

    def get_ports_for_agent(self, agent_id: int) -> List[int]:
        """Get available ports for a given agent_id"""
        return self.agent_to_ports.get(agent_id, [])


from os import cpu_count

from oasis.inference.inference_thread import SharedMemory

inference_log = logging.getLogger(name="inference")
inference_log.setLevel("DEBUG")

file_handler = logging.FileHandler("inference.log")
file_handler.setLevel("DEBUG")
file_handler.setFormatter(
    logging.Formatter("%(levelname)s - %(asctime)s - %(name)s - %(message)s"))
inference_log.addHandler(file_handler)


class InferencerManager:

    def __init__(
        self,
        channel,
        model_type: str,
        model_path: str,
        stop_tokens: List[str],
        server_url: List[Dict],
        port_ranges: Optional[Dict[Tuple[int, int], List[int]]] = None,
        timeout: int = 300,  # Timeout in seconds
        threads_per_port: int = 20,
        max_workers: int = 80,
    ):
        self.count = 0
        self.channel = channel
        self.threads: Dict[int, InferenceThread] = {}
        self.lock = asyncio.Lock(
        )  # Use asyncio.Lock for async synchronization
        self.stop_event = asyncio.Event()
        self.count = 0
        self.timeout = timeout

        # Default configuration: all agents can access all ports
        if port_ranges is None:
            # Extract all ports from server_url
            all_ports = []
            for url_config in server_url:
                all_ports.extend(url_config.get("ports", []))

            # Create default configuration where all agents (0 to max int) can access all ports
            port_ranges = {(0, sys.maxsize): all_ports}

        # Initialize PortManager
        self.port_manager = PortManager(port_ranges)

        # Initialize threads
        self._initialize_threads(server_url, model_type, model_path,
                                 stop_tokens, max_workers, threads_per_port)

        # Performance metrics
        self.metrics = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'average_processing_time': 0.0
        }

        # ThreadPoolExecutor for running blocking operations
        self.executor = ThreadPoolExecutor(max_workers=len(self.threads))

    def _initialize_threads(self, server_url, model_type, model_path,
                            stop_tokens, max_workers, threads_per_port):
        # """Initialize inference threads"""
        # for url_config in server_url:
        #     host = url_config["host"]
        #     for port in url_config["ports"]:
        #         try:
        #             _url = f"http://{host}:{port}/v1"
        #             shared_memory = SharedMemory()
        #             thread = InferenceThread(
        #                 model_path=model_path,
        #                 server_url=_url,
        #                 stop_tokens=stop_tokens,
        #                 model_type=model_type,
        #                 temperature=0.0,
        #                 shared_memory=shared_memory,
        #             )
        #             self.threads[port] = thread
        #         except Exception as e:
        #             logger.error(f"Failed to initialize thread for port {port}: {e}")

        # Check if max_workers is set to a reasonable value
        if max_workers < 1:
            inference_log.error(
                "Max workers must be at least 1. Setting to 1.")
            max_workers = 1
        # For IO bound tasks, max_workers should be set to a higher value
        # between 5 and 20 times the number of CPUs
        elif max_workers > cpu_count() * 20:
            inference_log.warning(
                f"Max workers is higher than recommended value. Setting to "
                f"{cpu_count() * 20}.")
            max_workers = cpu_count() * 20

        # Check if threads_per_port is set to a reasonable value
        total_ports = 0
        for url in server_url:
            total_ports += len(url["ports"])
        if total_ports * threads_per_port > max_workers:
            threads_per_port = max(max_workers // total_ports, 1)
            inference_log.warning(
                f"Total threads exceeds max workers. Setting threads per port "
                f"to {threads_per_port}.")
        if threads_per_port < 1:
            inference_log.error(
                "Threads per port must be at least 1. Setting to 1.")
            threads_per_port = 1

        for url in server_url:
            host = url["host"]
            for port in url["ports"]:
                _url = f"http://{host}:{port}/v1"
                thread = [
                    InferenceThread(
                        model_path=model_path,
                        server_url=_url,
                        stop_tokens=stop_tokens,
                        model_type=model_type,
                        temperature=0.0,
                        shared_memory=SharedMemory(),
                    ) for _ in range(threads_per_port)
                ]
                for t in thread:
                    self.threads[port] = t

    async def _find_available_thread(
            self,
            agent_id: int) -> Tuple[Optional[InferenceThread], Optional[int]]:
        """Find an available thread for the given agent_id"""
        available_ports = self.port_manager.get_ports_for_agent(agent_id)
        current_time = time.time()

        for port in available_ports:
            thread = self.threads.get(port)
            if thread is None:
                continue

            async with self.lock:
                if (not thread.shared_memory.Busy
                        or (current_time - thread.shared_memory.last_active)
                        > self.timeout):
                    if thread.shared_memory.Busy:
                        thread.shared_memory = SharedMemory()
                        logger.warning(
                            f"Reset thread on port {port} due to timeout")

                    return thread, port

        return None, None

    async def _process_completed_tasks(self):
        """Process completed inference tasks"""
        for port, thread in self.threads.items():
            async with self.lock:
                if thread.shared_memory.Done:
                    try:
                        await self.channel.send_to(
                            (thread.shared_memory.Message_ID,
                             thread.shared_memory.Response,
                             thread.shared_memory.Agent_ID))

                        # Update metrics
                        self.metrics['successful_requests'] += 1
                        logger.debug(
                            f"Processed completed task on port {port}")

                    except Exception as e:
                        logger.error(
                            f"Error sending response for port {port}: {e}")
                        self.metrics['failed_requests'] += 1
                    finally:
                        # Reset thread state
                        thread.shared_memory = SharedMemory()
                        thread.shared_memory.last_active = time.time()

    async def _handle_new_request(self):
        """Handle new incoming requests"""
        try:
            message = await asyncio.wait_for(self.channel.receive_from(),
                                             timeout=0.1)
        except asyncio.TimeoutError:
            # No new message received within the timeout
            return
        except Exception as e:
            logger.error(f"Error receiving message: {e}")
            return

        agent_id = int(message[2])
        start_time = time.time()

        available_thread, port = await self._find_available_thread(agent_id)

        if available_thread:
            async with self.lock:
                try:
                    available_thread.shared_memory.Message_ID = message[0]
                    available_thread.shared_memory.Message = message[1]
                    available_thread.shared_memory.Agent_ID = message[2]
                    available_thread.shared_memory.Busy = True
                    available_thread.shared_memory.last_active = time.time()

                    self.count += 1
                    self.metrics['total_requests'] += 1

                    # Update average processing time
                    processing_time = time.time() - start_time
                    self.metrics['average_processing_time'] = (
                        (self.metrics['average_processing_time'] *
                         (self.count - 1) + processing_time) / self.count)

                    logger.info(
                        f"Assigned message {self.count} to port {port} for agent {agent_id}"
                    )

                    # Start the inference in a separate thread
                    asyncio.create_task(
                        self._run_inference(available_thread, message))

                except Exception as e:
                    logger.error(
                        f"Error processing request for agent {agent_id}: {e}")
                    self.metrics['failed_requests'] += 1
                    # Requeue the message on failure
                    await self.channel.receive_queue.put(message)
        else:
            # No available threads; requeue the message
            await self.channel.receive_queue.put(message)

    async def _run_inference(self, thread: InferenceThread,
                             message: Tuple[str, str, str]):
        """Run inference in a separate thread and update shared_memory"""
        try:
            await asyncio.get_event_loop().run_in_executor(
                self.executor,
                thread.run,  # Assuming `run` is a blocking method
            )
            async with self.lock:
                thread.shared_memory.Done = True
        except Exception as e:
            logger.error(f"Inference error on thread {thread.server_url}: {e}")
            async with self.lock:
                thread.shared_memory.Done = True
                thread.shared_memory.Response = f"Error: {e}"
        finally:
            thread.shared_memory.Busy = False
            thread.shared_memory.last_active = time.time()

    async def run(self):
        """Main run loop"""
        # Start all inference threads
        for port, thread in self.threads.items():
            # Start each thread in the ThreadPoolExecutor
            asyncio.get_event_loop().run_in_executor(self.executor, thread.run)

        # Create background tasks
        process_tasks_task = asyncio.create_task(
            self._process_completed_tasks_loop())
        handle_requests_task = asyncio.create_task(
            self._handle_requests_loop())

        try:
            await asyncio.wait([process_tasks_task, handle_requests_task],
                               return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            logger.info("Inference manager run task cancelled")
        except Exception as e:
            logger.error(f"Error in main run loop: {e}")
        finally:
            await self.stop()

    async def _process_completed_tasks_loop(self):
        """Continuously process completed tasks"""
        while not self.stop_event.is_set():
            await self._process_completed_tasks()
            await asyncio.sleep(0.1)  # Adjust as needed

    async def _handle_requests_loop(self):
        """Continuously handle incoming requests"""
        while not self.stop_event.is_set():
            await self._handle_new_request()
            await asyncio.sleep(0.1)  # Adjust as needed

    async def stop(self):
        """Stop all inference threads and perform cleanup"""
        self.stop_event.set()
        for thread in self.threads.values():
            thread.alive = False  # Ensure threads exit their run loops

        self.executor.shutdown(wait=True)

        # Log final metrics
        logger.info(f"Final metrics: {self.metrics}")

    def get_metrics(self) -> dict:
        """Retrieve performance metrics"""
        return self.metrics
