#ifndef _UDP_H_
#define _UDP_H_

#include<stdatomic.h>
void udp_init(atomic_bool* running);

void udp_send_sample(float v);

void udp_cleanup(void);


#endif