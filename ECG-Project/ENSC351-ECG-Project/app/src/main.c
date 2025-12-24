#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include<stdbool.h>
#include<stdint.h>
#include<stdatomic.h>
#include<unistd.h>
#include<fcntl.h>
#include<sys/ioctl.h>
#include<linux/spi/spidev.h>
#include<pthread.h>
#include<time.h>
#include "adc.h"
#include "udp.h"

atomic_bool running = false;
int main(){


atomic_store(&running,true);
adcthread_init(&running);
udp_init(&running);

while(running == true){
    sleep(1);
}

adcthread_cleanup();
udp_cleanup();

}