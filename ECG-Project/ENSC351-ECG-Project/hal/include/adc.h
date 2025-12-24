
#ifndef adc_h
#define adc_h
#include<stdatomic.h>
void adcthread_init(atomic_bool* running);
void adcthread_cleanup(void);

#endif