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


const char* dev = "/dev/spidev0.0";
uint8_t mode = 0; // SPI mode 0
uint8_t bits = 8;
uint32_t speed = 250000;
int fd = 0;
pthread_t adc_sampler;
atomic_bool * running_adc = NULL;

static int read_ch(int fd, int ch, uint32_t speed_hz){
   uint8_t tx[3] = { (uint8_t)(0x06 | ((ch & 0x04) >> 2)),
 (uint8_t)((ch & 0x03) << 6),
 0x00 };

uint8_t rx[3] = { 0 };

struct spi_ioc_transfer tr = {
 .tx_buf = (unsigned long)tx,
 .rx_buf = (unsigned long)rx,
 .len = 3,
 .speed_hz = speed_hz,
 .bits_per_word = 8,
 .cs_change = 0
 };

if (ioctl(fd, SPI_IOC_MESSAGE(1), &tr) < 1) return -1;
return ((rx[1] & 0x0F) << 8) | rx[2]; 


}

void* sampler(void* arg){

    const double Fs = 2000.0;  // sampling frequency
    const useconds_t Ts = (useconds_t)(1e6 / Fs);

    while(atomic_load(running_adc) == true){
        int ch1 = read_ch(fd,1,speed);
        printf("%d\n",ch1);
            //     printf("%d\n",ch1);
            float v = (ch1/ 4095.0f) * 3.3f;
            //printf("%f\n",v);
            udp_send_sample(v);    // *** THIS STREAMS THE SAMPLE ***
        

        usleep(Ts);

    }



}


int openFile(void){
    fd = open(dev, O_RDWR);
    if (fd < 0) { perror("open"); return 1; }
    if (ioctl(fd, SPI_IOC_WR_MODE, &mode) == -1) { perror("mode"); return
    1; }

    if (ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, &bits) == -1) { perror("bpw");
    return 1; }
    if (ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed) == -1)
    { perror("speed"); return 1; }
}

void adcthread_init(atomic_bool* running){
    openFile();
    running_adc = running;
    pthread_create(&adc_sampler,NULL,sampler,NULL);
}

void adcthread_cleanup(void){
    pthread_join(adc_sampler,NULL);
    close(fd);
}